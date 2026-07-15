from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="WEBSHELL_", case_sensitive=False, extra="ignore"
    )

    app_name: str = "WebShell"
    environment: str = "development"
    data_dir: Path = Path(".data")
    database_url: str = "sqlite+aiosqlite:///.data/webshell.db"
    auto_create_schema: bool = True
    credential_key_path: Path = Path(".data/credentials.key")
    session_cookie: str = "webshell_session"
    cookie_secure: bool = False
    session_idle_seconds: int = 12 * 60 * 60
    session_absolute_seconds: int = 7 * 24 * 60 * 60
    secret_cache_seconds: int = 12 * 60 * 60
    ssh_connect_timeout: int = 15
    ssh_keepalive_seconds: int = 20
    enforce_destination_rules: bool = False
    max_terminals_per_user: int = 5
    tmux_history_limit: int = 50_000
    max_upload_bytes: int = 20 * 1024 * 1024 * 1024
    max_preview_bytes: int = 2 * 1024 * 1024
    trusted_origins: List[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    def prepare(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.credential_key_path.parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.prepare()
    return settings


def reset_settings() -> None:
    get_settings.cache_clear()
