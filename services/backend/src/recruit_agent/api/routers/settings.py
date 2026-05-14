from __future__ import annotations

from time import perf_counter

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from recruit_agent.agent_runtime.providers import AnthropicProvider, OpenAIProvider, ProviderConfig, ProviderError
from recruit_agent.agent_runtime.types import LLMMessage, LLMRequest
from recruit_agent.api.deps import get_container, get_session
from recruit_agent.core.settings import AppSettings
from recruit_agent.repositories import SettingsRepository
from recruit_agent.schemas.domain import ProviderConfigUpdate, ProviderHealthcheckRead, SettingsSnapshotRead, SettingsSnapshotUpdate
from recruit_agent.services.container import AppContainer

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _runtime_scene_account(settings: AppSettings) -> str:
    provider_config = settings.provider_config or {}
    return str(provider_config.get("site_account") or "本机场景 01")


def _runtime_user_profile(settings: AppSettings) -> dict[str, str | None]:
    provider_config = settings.provider_config or {}
    profile = provider_config.get("user_profile")
    if not isinstance(profile, dict):
        profile = {}
    nickname = str(profile.get("nickname") or provider_config.get("operator_nickname") or "招聘方").strip() or "招聘方"
    avatar_url = _normalize_optional_string(
        str(profile.get("avatarUrl") or profile.get("avatar_url") or provider_config.get("operator_avatar_url") or "")
    )
    return {"nickname": nickname, "avatarUrl": avatar_url}


def _normalize_optional_string(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _to_desktop_settings(settings: AppSettings) -> SettingsSnapshotRead:
    return SettingsSnapshotRead.model_validate(
        {
            "locale": "en-US",
            "timezone": "Asia/Shanghai",
            "intranetEnabled": settings.feature_flags.enable_intranet_sync,
            "desktopApprovalsOnly": settings.approval_source == "desktop_app",
            "autonomyEnabled": settings.feature_flags.enable_autonomy,
            "skill_health_autonomy_interval_seconds": settings.skill_health_autonomy_interval_seconds,
            "approval_source": settings.approval_source,
            "feature_flags": settings.feature_flags.model_dump(),
            "provider_config": settings.provider_config,
            "providers": [
                {
                    "kind": "openai-compatible",
                    "name": "主 OpenAI 接口",
                    "model": settings.provider_config.get("openai_model", "gpt-5.4"),
                    "enabled": bool(settings.provider_config.get("openai_enabled", True)),
                    "temperature": 0.2,
                    "baseUrl": settings.provider_config.get("openai_base_url", "https://api.openai.com/v1"),
                    "apiKey": settings.provider_config.get("openai_api_key"),
                    "timeoutSeconds": int(settings.provider_config.get("openai_timeout_seconds", 180) or 180),
                },
                {
                    "kind": "anthropic",
                    "name": "备用 Anthropic 接口",
                    "model": settings.provider_config.get("anthropic_model", "claude-sonnet-4"),
                    "enabled": bool(settings.provider_config.get("anthropic_enabled", False)),
                    "temperature": 0.2,
                    "baseUrl": settings.provider_config.get("anthropic_base_url", "https://api.anthropic.com"),
                    "apiKey": settings.provider_config.get("anthropic_api_key"),
                    "timeoutSeconds": int(settings.provider_config.get("anthropic_timeout_seconds", 180) or 180),
                },
            ],
            "intranetSync": {
                "enabled": settings.feature_flags.enable_intranet_sync,
                "baseUrl": settings.intranet_sync.base_url,
                "apiPath": settings.intranet_sync.api_path,
                "timeoutSeconds": settings.intranet_sync.timeout_seconds,
            },
            "platform": {
                "name": "本地执行配置",
                "account": _runtime_scene_account(settings),
                "cooldownDays": settings.provider_config.get("cooldown_days", 30),
                "allowOutboundMessaging": settings.feature_flags.enable_outbound_messaging,
                "maxConcurrentRuns": settings.provider_config.get("max_concurrent_runs", 1),
                "minFunnelCandidates": settings.provider_config.get("autonomy_min_funnel_candidates", 0),
            },
            "userProfile": _runtime_user_profile(settings),
        }
    )


async def _sync_autonomy_runtime(request: Request, settings: AppSettings) -> None:
    autonomy = getattr(request.app.state, "autonomy_loop", None)
    if autonomy is None:
        return
    # The settings toggle controls background sourcing semantics, but the
    # queue consumer must stay alive so manual Autonomous runs can execute.
    autonomy.enabled = True
    autonomy.health_sweep_enabled = settings.feature_flags.enable_skill_health_autonomy
    autonomy.health_sweep_interval = float(settings.skill_health_autonomy_interval_seconds)
    if not autonomy.is_running():
        await autonomy.start()


@router.get("", response_model=SettingsSnapshotRead)
def get_settings(
    container: AppContainer = Depends(get_container),
    session: Session = Depends(get_session),
) -> SettingsSnapshotRead:
    stored = SettingsRepository(session).load(container.settings)
    resolved = AppSettings.model_validate(stored.model_dump())
    return _to_desktop_settings(resolved)


@router.patch("", response_model=SettingsSnapshotRead)
async def update_settings(
    payload: SettingsSnapshotUpdate,
    request: Request,
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
    if payload.autonomyEnabled is not None:
        data["feature_flags"]["enable_autonomy"] = payload.autonomyEnabled
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
        if "maxConcurrentRuns" in platform_data:
            provider_config["max_concurrent_runs"] = max(int(platform_data["maxConcurrentRuns"]), 1)
        if "minFunnelCandidates" in platform_data:
            provider_config["autonomy_min_funnel_candidates"] = max(int(platform_data["minFunnelCandidates"]), 0)
    if payload.userProfile is not None:
        profile_data = payload.userProfile.model_dump(exclude_none=True)
        provider_config = data.setdefault("provider_config", {})
        user_profile = dict(provider_config.get("user_profile") or {})
        if "nickname" in profile_data:
            user_profile["nickname"] = str(profile_data["nickname"]).strip() or "招聘方"
        if "avatarUrl" in profile_data:
            user_profile["avatarUrl"] = _normalize_optional_string(profile_data["avatarUrl"])
        provider_config["user_profile"] = user_profile
    if payload.providers is not None:
        provider_config = data.setdefault("provider_config", {})
        for provider in payload.providers:
            if provider.kind == "openai-compatible":
                provider_config["openai_model"] = provider.model
                normalized_base_url = _normalize_optional_string(provider.baseUrl)
                if normalized_base_url is None:
                    provider_config.pop("openai_base_url", None)
                else:
                    provider_config["openai_base_url"] = normalized_base_url
                provider_config["openai_api_key"] = _normalize_optional_string(provider.apiKey)
                provider_config["openai_enabled"] = provider.enabled
                if provider.timeoutSeconds is not None:
                    provider_config["openai_timeout_seconds"] = max(int(provider.timeoutSeconds), 1)
            elif provider.kind == "anthropic":
                provider_config["anthropic_model"] = provider.model
                normalized_base_url = _normalize_optional_string(provider.baseUrl)
                if normalized_base_url is None:
                    provider_config.pop("anthropic_base_url", None)
                else:
                    provider_config["anthropic_base_url"] = normalized_base_url
                provider_config["anthropic_api_key"] = _normalize_optional_string(provider.apiKey)
                provider_config["anthropic_enabled"] = provider.enabled
                if provider.timeoutSeconds is not None:
                    provider_config["anthropic_timeout_seconds"] = max(int(provider.timeoutSeconds), 1)
    if payload.approval_source is not None:
        data["approval_source"] = payload.approval_source
    if payload.feature_flags is not None:
        data["feature_flags"].update(payload.feature_flags.model_dump(exclude_unset=True))
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
    await _sync_autonomy_runtime(request, resolved)
    return _to_desktop_settings(resolved)


@router.put("", response_model=SettingsSnapshotRead)
async def replace_settings(
    payload: SettingsSnapshotUpdate,
    request: Request,
    container: AppContainer = Depends(get_container),
    session: Session = Depends(get_session),
) -> SettingsSnapshotRead:
    return await update_settings(payload, request=request, container=container, session=session)


@router.post("/providers/check", response_model=ProviderHealthcheckRead)
def check_provider(payload: ProviderConfigUpdate) -> ProviderHealthcheckRead:
    provider_config = ProviderConfig(
        provider_name=payload.kind.replace("-", "_"),
        model=payload.model,
        base_url=_normalize_optional_string(payload.baseUrl),
        api_key=_normalize_optional_string(payload.apiKey),
        timeout_seconds=max(int(payload.timeoutSeconds or 30), 1),
    )
    if not provider_config.base_url:
        return ProviderHealthcheckRead(ok=False, status="missing_base_url", message="Base URL is required.")
    if not provider_config.api_key:
        return ProviderHealthcheckRead(ok=False, status="missing_api_key", message="API key is required.")

    request = LLMRequest(
        id="settings-provider-healthcheck",
        turn_id="settings-provider-healthcheck",
        invocation_id="settings-provider-healthcheck",
        messages=[LLMMessage(role="user", content="Reply with OK.")],
        model=payload.model,
        max_tokens=8,
        temperature=0,
    )
    provider = AnthropicProvider(provider_config) if payload.kind == "anthropic" else OpenAIProvider(provider_config)
    started = perf_counter()
    try:
        provider.invoke(request)
    except ProviderError as exc:
        return ProviderHealthcheckRead(
            ok=False,
            status="failed",
            latencyMs=round((perf_counter() - started) * 1000),
            message=str(exc),
        )
    return ProviderHealthcheckRead(
        ok=True,
        status="healthy",
        latencyMs=round((perf_counter() - started) * 1000),
        message="Provider responded.",
    )
