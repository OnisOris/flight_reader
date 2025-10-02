from functools import lru_cache

from pydantic import Field

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # -------- Параметры API --------
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8001, alias="API_PORT")
    api_prefix: str = Field(default="/api", alias="API_PREFIX")

    # -------- Параметры базы данных --------
    db_host: str = Field(default="localhost", alias="DB_HOST")
    db_port: int = Field(default=5432, alias="DB_PORT")
    db_name: str = Field(default="flight_reader", alias="DB_NAME")
    db_user: str = Field(default="flight_reader", alias="DB_USER")
    db_password: str = Field(default="flight_reader_password", alias="DB_PASSWORD")
    db_echo: bool = Field(default=False, alias="DB_ECHO")

    # -------- Аутентификация --------
    auth_enabled: bool = Field(default=False, alias="AUTH_ENABLED")
    keycloak_server_url: str | None = Field(default=None, alias="KEYCLOAK_SERVER_URL")
    keycloak_realm: str | None = Field(default=None, alias="KEYCLOAK_REALM")
    keycloak_client_id: str | None = Field(default=None, alias="KEYCLOAK_CLIENT_ID")
    keycloak_audience: str | None = Field(default=None, alias="KEYCLOAK_AUDIENCE")
    keycloak_issuer: str | None = Field(default=None, alias="KEYCLOAK_ISSUER")
    keycloak_jwks_url: str | None = Field(default=None, alias="KEYCLOAK_JWKS_URL")
    keycloak_expected_algorithms: tuple[str, ...] = Field(
        default=("RS256",), alias="KEYCLOAK_EXPECTED_ALGORITHMS"
    )
    keycloak_partner_role: str = Field(default="partner", alias="KEYCLOAK_PARTNER_ROLE")
    keycloak_regulator_role: str = Field(
        default="regulator", alias="KEYCLOAK_REGULATOR_ROLE"
    )
    keycloak_partner_operator_claim: str = Field(
        default="partner_operator_codes",
        alias="KEYCLOAK_PARTNER_OPERATOR_CLAIM",
    )

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def resolved_keycloak_issuer(self) -> str | None:
        if self.keycloak_issuer:
            return self.keycloak_issuer.rstrip("/")
        if self.keycloak_server_url and self.keycloak_realm:
            return f"{self.keycloak_server_url.rstrip('/')}/realms/{self.keycloak_realm}"
        return None

    @property
    def resolved_keycloak_jwks_url(self) -> str | None:
        if self.keycloak_jwks_url:
            return self.keycloak_jwks_url
        issuer = self.resolved_keycloak_issuer
        if issuer:
            return f"{issuer}/protocol/openid-connect/certs"
        return None

    @property
    def resolved_keycloak_audience(self) -> str | None:
        if self.keycloak_audience:
            return self.keycloak_audience
        return self.keycloak_client_id


@lru_cache
def get_settings() -> "Settings":
    return Settings()
