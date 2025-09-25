from typing import List, Optional

from pydantic import Field

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # -------- API --------
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8001, alias="API_PORT")
    api_prefix: str = Field(default="/api", alias="API_PREFIX")
