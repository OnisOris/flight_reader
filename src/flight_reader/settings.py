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

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


@lru_cache
def get_settings() -> "Settings":
    return Settings()
