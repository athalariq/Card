from __future__ import annotations

from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables and an optional .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="LARPCARD_",
        case_sensitive=False,
        extra="ignore",
    )

    discord_token: SecretStr = SecretStr("")
    database_url: str = "postgresql+asyncpg://larpcard:larpcard@localhost:5432/larpcard"
    redis_url: str = "redis://localhost:6379/0"
    asset_root: Path = Path("assets")
    log_level: str = "INFO"
    sync_commands_on_startup: bool = True
    dev_guild_ids: list[int] = Field(default_factory=list)
    catalog_cache_seconds: int = Field(default=60, ge=1, le=3600)
    drop_min_cards: int = Field(default=2, ge=1, le=4)
    drop_max_cards: int = Field(default=4, ge=1, le=4)
    drop_cooldown_seconds: int = Field(default=300, ge=0)
    claim_window_seconds: int = Field(default=60, ge=10, le=900)

    @model_validator(mode="after")
    def validate_drop_range(self) -> Settings:
        if self.drop_min_cards > self.drop_max_cards:
            raise ValueError("drop_min_cards cannot exceed drop_max_cards")
        return self
