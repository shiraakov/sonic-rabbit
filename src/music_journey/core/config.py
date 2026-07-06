"""Runtime configuration, loaded from environment / .env."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # protected_namespaces=() so `model_id` doesn't collide with pydantic's "model_" namespace.
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", protected_namespaces=()
    )

    data_dir: str = "data"
    model_id: str = "gemini/gemini-2.5-flash"
    gemini_api_key: str = ""


settings = Settings()
