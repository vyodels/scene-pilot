from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path
from typing import Any

from pydantic import AliasChoices, BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class FeatureFlags(BaseModel):
    enable_autonomy: bool = False
    enable_skill_health_autonomy: bool = False
    enable_system_commands: bool = False
    enable_intranet_sync: bool = False
    enable_outbound_messaging: bool = False


class ProviderRuntimeSettings(BaseModel):
    openai_model: str = "gpt-5.4"
    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str | None = None
    openai_timeout_seconds: int = 180
    anthropic_model: str = "claude-sonnet-4"
    anthropic_base_url: str = "https://api.anthropic.com"
    anthropic_api_key: str | None = None
    anthropic_timeout_seconds: int = 180
    site_account: str = Field(default="本机场景 01", validation_alias=AliasChoices("site_account", "boss_account"))
    cooldown_days: int = 30
    autonomy_min_funnel_candidates: int = 0
    autonomy_sourcing_cooldown_seconds: int = 60

    def get(self, name: str, default: Any = None) -> Any:
        return getattr(self, name, default)


class IntranetSyncSettings(BaseModel):
    base_url: str | None = None
    api_token: str | None = None
    api_path: str = "/api/recruit-agent/sync"
    timeout_seconds: int = 10


def _apply_env_alias_prefix() -> None:
    for key, value in list(os.environ.items()):
        if not key.startswith("RECRUIT_AGENT_"):
            continue
        alias_key = f"RECRUIT_AGENT_{key[len('RECRUIT_AGENT_'):]}"
        os.environ.setdefault(alias_key, value)


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RECRUIT_AGENT_",
        env_file=".env",
        env_nested_delimiter="__",
        extra="ignore",
    )

    def __init__(self, **values: Any) -> None:
        _apply_env_alias_prefix()
        super().__init__(**values)

    app_name: str = "Recruit Agent"
    environment: str = "development"
    host: str = "127.0.0.1"
    port: int = 8741
    data_dir: str = "./data"
    database_url: str = "sqlite:///./recruit-agent.db"
    database_echo: bool = False
    scheduler_lock_timeout_seconds: int = 300
    skill_health_autonomy_interval_seconds: int = 300
    approval_source: str = "desktop_app"
    default_platform: str = "site"
    feature_flags: FeatureFlags = Field(default_factory=FeatureFlags)
    provider_config: dict[str, Any] = Field(default_factory=dict)
    intranet_sync: IntranetSyncSettings = Field(default_factory=IntranetSyncSettings)

    def resolved_data_dir(self) -> Path:
        return Path(self.data_dir).expanduser()

    def resolved_database_url(self) -> str:
        url = make_url(self.database_url)
        if url.drivername.startswith("sqlite") and url.database:
            database = url.database
            if database in {".", "./recruit-agent.db", "recruit-agent.db", "./recruit-agent.db", "recruit-agent.db"}:
                data_dir = self.resolved_data_dir()
                data_dir.mkdir(parents=True, exist_ok=True)
                return f"sqlite:///{(data_dir / 'recruit-agent.db').resolve()}"

            database_path = Path(database).expanduser()
            if not database_path.is_absolute():
                database_path = self.resolved_data_dir() / database_path
            database_path.parent.mkdir(parents=True, exist_ok=True)
            return f"sqlite:///{database_path.resolve()}"
        return self.database_url

    def with_overrides(self, **updates: Any) -> "AppSettings":
        data = self.model_dump()
        data.update(updates)
        return AppSettings.model_validate(data)

    def provider_runtime_settings(self) -> ProviderRuntimeSettings:
        return ProviderRuntimeSettings.model_validate(self.provider_config)

    def build_provider_config(self, provider_name: str):
        from recruit_agent.agent_runtime.providers import ProviderConfig

        provider_name = provider_name.replace("-", "_").lower()
        runtime_settings = self.provider_runtime_settings()
        if provider_name in {"openai", "openai_compatible"}:
            return ProviderConfig(
                provider_name="openai_compatible",
                model=runtime_settings.openai_model,
                base_url=runtime_settings.openai_base_url,
                api_key=runtime_settings.openai_api_key,
                timeout_seconds=runtime_settings.openai_timeout_seconds,
            )
        if provider_name == "anthropic":
            return ProviderConfig(
                provider_name="anthropic",
                model=runtime_settings.anthropic_model,
                base_url=runtime_settings.anthropic_base_url,
                api_key=runtime_settings.anthropic_api_key,
                timeout_seconds=runtime_settings.anthropic_timeout_seconds,
            )
        raise ValueError(f"Unknown provider name: {provider_name}")


@lru_cache(maxsize=1)
def load_settings() -> AppSettings:
    _apply_env_alias_prefix()
    return AppSettings()
