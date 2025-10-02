"""Keycloak-based authentication utilities for FastAPI routers."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Annotated, Any, Iterable

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import jwt
from jose.exceptions import ExpiredSignatureError, JWTError
from sqlalchemy import select
from sqlalchemy.orm import Session

from flight_reader.db import get_session
from flight_reader.db_models import User
from flight_reader.settings import get_settings

logger = logging.getLogger(__name__)


class UserRole(str, Enum):
    """Internal representation of supported user roles."""

    ADMIN = "admin"
    REGULATOR = "regulator"
    PARTNER = "partner"

    @classmethod
    def from_value(cls, raw: str) -> "UserRole":
        try:
            return cls(raw)
        except ValueError as exc:  # pragma: no cover - defensive branch
            raise ValueError(f"Unsupported user role: {raw!r}") from exc


@dataclass(frozen=True)
class AuthenticatedUser:
    """Normalized user payload shared with FastAPI endpoints."""

    id: int
    auth_id: str
    role: UserRole
    email: str | None
    name: str | None
    allowed_operator_codes: tuple[str, ...]
    claims: dict[str, Any]


class AuthenticationError(RuntimeError):
    """Raised when token validation or user provisioning fails."""


class KeycloakAuthenticator:
    """Validate JWTs issued by Keycloak and map them onto application users."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._jwks_cache: dict[str, Any] | None = None
        self._jwks_expires_at: float = 0.0
        self._jwks_min_ttl = 60.0

    def validate_token(self, token: str) -> dict[str, Any]:
        """Decode and validate a JWT issued by Keycloak."""

        if not token:
            raise AuthenticationError("Empty bearer token")

        jwk = self._get_signing_key(token)
        issuer = self._settings.resolved_keycloak_issuer
        audience = self._settings.resolved_keycloak_audience

        try:
            claims = jwt.decode(
                token,
                jwk,
                algorithms=list(self._settings.keycloak_expected_algorithms),
                issuer=issuer,
                audience=audience,
                options={"verify_aud": audience is not None},
            )
        except ExpiredSignatureError as exc:
            raise AuthenticationError("Token has expired") from exc
        except JWTError as exc:
            raise AuthenticationError("Invalid token") from exc

        return claims

    def _get_signing_key(self, token: str) -> dict[str, Any]:
        """Resolve the JWK matching the token header."""

        try:
            header = jwt.get_unverified_header(token)
        except JWTError as exc:  # pragma: no cover - jose raises JWTError
            raise AuthenticationError("Failed to parse token header") from exc

        kid = header.get("kid")
        if not kid:
            raise AuthenticationError("Token is missing the 'kid' header")

        jwks = self._load_jwks()
        key = next((item for item in jwks.get("keys", []) if item.get("kid") == kid), None)
        if key is not None:
            return key

        # Key rotation – refresh cache and try again once
        self._jwks_cache = None
        jwks = self._load_jwks()
        key = next((item for item in jwks.get("keys", []) if item.get("kid") == kid), None)
        if key is None:
            raise AuthenticationError("Signing key not found")
        return key

    def _load_jwks(self) -> dict[str, Any]:
        now = time.monotonic()
        if self._jwks_cache and now < self._jwks_expires_at:
            return self._jwks_cache

        jwks_url = self._settings.resolved_keycloak_jwks_url
        if not jwks_url:
            raise AuthenticationError("Keycloak JWKS URL is not configured")

        try:
            response = httpx.get(jwks_url, timeout=5.0)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.error("Failed to download JWKS from %s: %s", jwks_url, exc)
            raise AuthenticationError("Unable to fetch Keycloak signing keys") from exc

        payload = response.json()
        cache_ttl = self._extract_cache_ttl(response.headers.get("cache-control"))
        self._jwks_cache = payload
        self._jwks_expires_at = now + max(cache_ttl, self._jwks_min_ttl)
        return payload

    @staticmethod
    def _extract_cache_ttl(cache_control: str | None) -> float:
        if not cache_control:
            return 300.0
        for directive in cache_control.split(","):
            directive = directive.strip().lower()
            if directive.startswith("max-age="):
                _, value = directive.split("=", 1)
                try:
                    return float(value)
                except ValueError:  # pragma: no cover - defensive branch
                    return 300.0
        return 300.0

    def ensure_user(self, session: Session, claims: dict[str, Any]) -> User:
        auth_id = claims.get("sub")
        if not auth_id:
            raise AuthenticationError("Token is missing 'sub' claim")

        resolved_role = self._resolve_role(claims)
        if resolved_role is None:
            raise AuthenticationError("User does not have a permitted role")

        stmt = select(User).where(User.auth_id == auth_id)
        user = session.execute(stmt).scalar_one_or_none()
        full_name = self._extract_name(claims)
        email = claims.get("email")

        if user is None:
            user = User(auth_id=auth_id, role=resolved_role.value, name=full_name, email=email)
            session.add(user)
            session.commit()
            logger.info("Provisioned user %s with role %s", auth_id, resolved_role.value)
        else:
            updated = False
            if user.role != resolved_role.value:
                user.role = resolved_role.value
                updated = True
            if full_name and user.name != full_name:
                user.name = full_name
                updated = True
            if email and user.email != email:
                user.email = email
                updated = True
            if updated:
                session.commit()
                logger.info("Updated user %s metadata", auth_id)

        return user

    @staticmethod
    def _extract_name(claims: dict[str, Any]) -> str | None:
        if claims.get("name"):
            return str(claims["name"])
        if claims.get("preferred_username"):
            return str(claims["preferred_username"])
        return None

    def _resolve_role(self, claims: dict[str, Any]) -> UserRole | None:
        roles = set(self._extract_roles(claims))
        if UserRole.ADMIN.value in roles:
            return UserRole.ADMIN
        if self._settings.keycloak_regulator_role in roles:
            return UserRole.REGULATOR
        if self._settings.keycloak_partner_role in roles:
            return UserRole.PARTNER
        return None

    def _extract_roles(self, claims: dict[str, Any]) -> Iterable[str]:
        roles: set[str] = set()
        realm_access = claims.get("realm_access") or {}
        if isinstance(realm_access, dict):
            realm_roles = realm_access.get("roles") or []
            if isinstance(realm_roles, (list, tuple, set)):
                roles.update(str(role) for role in realm_roles)
        client_id = self._settings.keycloak_client_id
        resource_access = claims.get("resource_access") or {}
        if isinstance(resource_access, dict) and client_id and client_id in resource_access:
            client_roles = resource_access[client_id].get("roles") or []
            if isinstance(client_roles, (list, tuple, set)):
                roles.update(str(role) for role in client_roles)
        direct_roles = claims.get("roles")
        if isinstance(direct_roles, (list, tuple, set)):
            roles.update(str(role) for role in direct_roles)
        return roles

    def extract_partner_operator_codes(
        self, claims: dict[str, Any], role: UserRole
    ) -> tuple[str, ...]:
        if role not in {UserRole.PARTNER}:
            return tuple()
        claim_name = self._settings.keycloak_partner_operator_claim
        raw_value = claims.get(claim_name)
        codes: set[str] = set()
        if isinstance(raw_value, str):
            codes.update(part.strip() for part in raw_value.split(",") if part.strip())
        elif isinstance(raw_value, (list, tuple, set)):
            codes.update(str(item).strip() for item in raw_value if str(item).strip())
        resource_access = claims.get("resource_access") or {}
        client_id = self._settings.keycloak_client_id
        if (
            not codes
            and isinstance(resource_access, dict)
            and client_id
            and client_id in resource_access
        ):
            client_claims = resource_access[client_id]
            nested = client_claims.get(claim_name)
            if isinstance(nested, str):
                codes.update(part.strip() for part in nested.split(",") if part.strip())
            elif isinstance(nested, (list, tuple, set)):
                codes.update(str(item).strip() for item in nested if str(item).strip())
        normalized = tuple(sorted({code.upper() for code in codes if code}))
        return normalized


_bearer_scheme = HTTPBearer(auto_error=False)
_authenticator = KeycloakAuthenticator()


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    session: Session = Depends(get_session),
) -> AuthenticatedUser:
    settings = get_settings()
    if not settings.auth_enabled:
        fallback = session.execute(select(User).order_by(User.id)).scalar_one_or_none()
        if fallback is None:
            fallback = User(auth_id="local-dev", role=UserRole.ADMIN.value, name="Local Dev")
            session.add(fallback)
            session.commit()
        return AuthenticatedUser(
            id=fallback.id,
            auth_id=fallback.auth_id,
            role=UserRole.from_value(fallback.role),
            email=fallback.email,
            name=fallback.name,
            allowed_operator_codes=tuple(),
            claims={},
        )

    if credentials is None or not credentials.scheme.lower() == "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    token = credentials.credentials
    try:
        claims = _authenticator.validate_token(token)
        user = _authenticator.ensure_user(session, claims)
        role = UserRole.from_value(user.role)
        operator_codes = _authenticator.extract_partner_operator_codes(claims, role)
    except AuthenticationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    return AuthenticatedUser(
        id=user.id,
        auth_id=user.auth_id,
        role=role,
        email=user.email,
        name=user.name,
        allowed_operator_codes=operator_codes,
        claims=claims,
    )


CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
"""Convenience alias for dependency injection."""
