from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from recruit_agent.api.deps import get_container
from recruit_agent.schemas.domain import McpPresetInstallRequest, McpPresetTemplateRead, McpServerCreate, McpServerRead, McpServerUpdate
from recruit_agent.services.container import AppContainer
from recruit_agent.services.mcp_registry import McpRegistryService, preset_templates

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


def _registry(container: AppContainer) -> McpRegistryService:
    return container.mcp_registry


def _reload_runtime(container: AppContainer) -> None:
    container.reload_settings(container.settings)


@router.get("/presets", response_model=list[McpPresetTemplateRead])
def list_mcp_presets(container: AppContainer = Depends(get_container)) -> list[McpPresetTemplateRead]:
    _ = container
    return [McpPresetTemplateRead.model_validate(item) for item in preset_templates()]


@router.post("/presets/{preset_key}/install", response_model=McpServerRead, status_code=201)
def install_mcp_preset(
    preset_key: str,
    payload: McpPresetInstallRequest,
    container: AppContainer = Depends(get_container),
) -> McpServerRead:
    try:
        server = _registry(container).install_preset(
            preset_key,
            server_key=payload.server_key,
            name=payload.name,
            endpoint=payload.endpoint,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _reload_runtime(container)
    return McpServerRead.model_validate(server)


@router.get("/servers", response_model=list[McpServerRead])
def list_mcp_servers(container: AppContainer = Depends(get_container)) -> list[McpServerRead]:
    return [McpServerRead.model_validate(item) for item in _registry(container).list_servers()]


@router.post("/servers", response_model=McpServerRead, status_code=201)
def create_mcp_server(
    payload: McpServerCreate,
    container: AppContainer = Depends(get_container),
) -> McpServerRead:
    try:
        server = _registry(container).create_server(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _reload_runtime(container)
    return McpServerRead.model_validate(server)


@router.patch("/servers/{server_id}", response_model=McpServerRead)
def update_mcp_server(
    server_id: str,
    payload: McpServerUpdate,
    container: AppContainer = Depends(get_container),
) -> McpServerRead:
    try:
        server = _registry(container).update_server(server_id, payload.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=404 if "not found" in str(exc).lower() else 400, detail=str(exc)) from exc
    _reload_runtime(container)
    return McpServerRead.model_validate(server)


@router.delete("/servers/{server_id}", status_code=204)
def delete_mcp_server(
    server_id: str,
    container: AppContainer = Depends(get_container),
) -> None:
    try:
        _registry(container).delete_server(server_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _reload_runtime(container)


@router.post("/servers/{server_id}/healthcheck", response_model=McpServerRead)
def healthcheck_mcp_server(
    server_id: str,
    container: AppContainer = Depends(get_container),
) -> McpServerRead:
    try:
        server = _registry(container).healthcheck_server(server_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _reload_runtime(container)
    return McpServerRead.model_validate(server)
