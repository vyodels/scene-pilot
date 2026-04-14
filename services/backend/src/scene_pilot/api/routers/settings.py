from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from scene_pilot.api.deps import get_container, get_session
from scene_pilot.core.settings import AppSettings
from scene_pilot.repositories import SettingsRepository
from scene_pilot.schemas.domain import SettingsSnapshotRead, SettingsSnapshotUpdate
from scene_pilot.services.container import AppContainer

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _runtime_scene_account(settings: AppSettings) -> str:
    provider_config = settings.provider_config or {}
    return str(provider_config.get("site_account") or provider_config.get("boss_account") or "本机场景 01")


def _to_desktop_settings(settings: AppSettings) -> SettingsSnapshotRead:
    return SettingsSnapshotRead.model_validate(
        {
            "locale": "en-US",
            "timezone": "Asia/Shanghai",
            "intranetEnabled": settings.feature_flags.enable_intranet_sync,
            "desktopApprovalsOnly": settings.approval_source == "desktop_app",
            "skill_health_autonomy_interval_seconds": settings.skill_health_autonomy_interval_seconds,
            "approval_source": settings.approval_source,
            "feature_flags": settings.feature_flags.model_dump(),
            "provider_config": settings.provider_config,
            "providers": [
                {
                    "kind": "openai-compatible",
                    "name": "主 OpenAI 接口",
                    "model": settings.provider_config.get("openai_model", "gpt-5.4"),
                    "enabled": True,
                    "temperature": 0.2,
                    "baseUrl": settings.provider_config.get("openai_base_url", "https://api.openai.com/v1"),
                },
                {
                    "kind": "anthropic",
                    "name": "备用 Anthropic 接口",
                    "model": settings.provider_config.get("anthropic_model", "claude-sonnet-4"),
                    "enabled": False,
                    "temperature": 0.2,
                    "baseUrl": settings.provider_config.get("anthropic_base_url", "https://api.anthropic.com"),
                },
            ],
            "intranetSync": {
                "enabled": settings.feature_flags.enable_intranet_sync,
                "baseUrl": settings.intranet_sync.base_url,
                "apiPath": settings.intranet_sync.api_path,
                "timeoutSeconds": settings.intranet_sync.timeout_seconds,
            },
            "platform": {
                "name": "运行时场景画像",
                "account": _runtime_scene_account(settings),
                "cooldownDays": settings.provider_config.get("cooldown_days", 30),
                "allowOutboundMessaging": settings.feature_flags.enable_outbound_messaging,
            },
        }
    )


@router.get("", response_model=SettingsSnapshotRead)
def get_settings(
    container: AppContainer = Depends(get_container),
    session: Session = Depends(get_session),
) -> SettingsSnapshotRead:
    stored = SettingsRepository(session).load(container.settings)
    resolved = AppSettings.model_validate(stored.model_dump())
    return _to_desktop_settings(resolved)


@router.patch("", response_model=SettingsSnapshotRead)
def update_settings(
    payload: SettingsSnapshotUpdate,
    container: AppContainer = Depends(get_container),
    session: Session = Depends(get_session),
) -> SettingsSnapshotRead:
    current = SettingsRepository(session).load(container.settings)
    data = current.model_dump()
    if payload.intranetEnabled is not None:
        data["feature_flags"]["enable_intranet_sync"] = payload.intranetEnabled
    if payload.intranetSync is not None:
        intranet_sync = data.setdefault("intranet_sync", {})
        sync_data = payload.intranetSync.model_dump(exclude_none=True)
        if "enabled" in sync_data:
            data["feature_flags"]["enable_intranet_sync"] = sync_data["enabled"]
        if "baseUrl" in sync_data:
            intranet_sync["base_url"] = sync_data["baseUrl"]
        if "apiPath" in sync_data:
            intranet_sync["api_path"] = sync_data["apiPath"]
        if "timeoutSeconds" in sync_data:
            intranet_sync["timeout_seconds"] = sync_data["timeoutSeconds"]
    if payload.desktopApprovalsOnly is not None:
        data["approval_source"] = "desktop_app" if payload.desktopApprovalsOnly else "hybrid"
    if payload.skill_health_autonomy_interval_seconds is not None:
        data["skill_health_autonomy_interval_seconds"] = payload.skill_health_autonomy_interval_seconds
    if payload.platform is not None:
        platform_data = payload.platform.model_dump(exclude_none=True)
        provider_config = data.setdefault("provider_config", {})
        if "account" in platform_data:
            provider_config["site_account"] = platform_data["account"]
        if "cooldownDays" in platform_data:
            provider_config["cooldown_days"] = platform_data["cooldownDays"]
        if "allowOutboundMessaging" in platform_data:
            data["feature_flags"]["enable_outbound_messaging"] = platform_data["allowOutboundMessaging"]
    if payload.providers is not None:
        provider_config = data.setdefault("provider_config", {})
        for provider in payload.providers:
            if provider.kind == "openai-compatible":
                provider_config["openai_model"] = provider.model
                provider_config["openai_base_url"] = provider.baseUrl
            elif provider.kind == "anthropic":
                provider_config["anthropic_model"] = provider.model
                provider_config["anthropic_base_url"] = provider.baseUrl
    if payload.approval_source is not None:
        data["approval_source"] = payload.approval_source
    if payload.feature_flags is not None:
        data["feature_flags"] = payload.feature_flags.model_dump()
    if payload.provider_config is not None:
        data["provider_config"] = payload.provider_config
        intranet_sync = data.setdefault("intranet_sync", {})
        legacy_intranet_base_url = payload.provider_config.get("intranet_base_url")
        if isinstance(legacy_intranet_base_url, str) and legacy_intranet_base_url.strip():
            intranet_sync["base_url"] = legacy_intranet_base_url.strip()
        legacy_timeout = payload.provider_config.get("intranet_timeout_seconds")
        if isinstance(legacy_timeout, int):
            intranet_sync["timeout_seconds"] = legacy_timeout

    saved = SettingsRepository(session).save(data)
    resolved = AppSettings.model_validate(saved.model_dump())
    container.reload_settings(resolved)
    return _to_desktop_settings(resolved)


@router.put("", response_model=SettingsSnapshotRead)
def replace_settings(
    payload: SettingsSnapshotUpdate,
    container: AppContainer = Depends(get_container),
    session: Session = Depends(get_session),
) -> SettingsSnapshotRead:
    return update_settings(payload, container=container, session=session)
