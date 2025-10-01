"""Примитивная токен-авторизация для API."""

from __future__ import annotations

from typing import Callable, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from flight_reader.settings import get_settings


_bearer_scheme = HTTPBearer(auto_error=False)


def get_auth_dependency() -> Optional[Callable[[], None]]:
    """Возвращает зависимость FastAPI для проверки Bearer-токена.

    Если в настройках не задан список токенов (`AUTH_TOKENS`), авторизация
    считается отключённой и возвращается ``None``.
    """

    tokens = set(get_settings().auth_token_list)
    if not tokens:
        return None

    async def _require_auth(
        credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    ) -> None:
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if credentials.credentials not in tokens:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    return _require_auth

