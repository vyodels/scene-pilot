from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, Query

from scene_pilot.api.deps import get_container
from scene_pilot.schemas import SyncBacklogRead, SyncFlushRead, SyncStatusRead
from scene_pilot.services.container import AppContainer

router = APIRouter(prefix="/api/sync", tags=["sync"])


@router.get("/status", response_model=SyncStatusRead)
def get_sync_status(
    container: AppContainer = Depends(get_container),
) -> SyncStatusRead:
    snapshot = container.sync.status_snapshot()
    return SyncStatusRead(**asdict(snapshot))


@router.get("/backlog", response_model=list[SyncBacklogRead])
def list_sync_backlog(
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    container: AppContainer = Depends(get_container),
) -> list[SyncBacklogRead]:
    items = container.sync.list_backlog(status=status, limit=limit, offset=offset)
    return [
        SyncBacklogRead(
            id=f"{item.item_type}:{item.item_id}",
            protocol_version=item.protocol_version,
            destination=str(item.target.get("kind") or "intranet"),
            item_type=item.item_type,
            item_id=item.item_id,
            payload=dict(item.payload),
            status=item.status,
            attempt_count=item.attempt_count,
            last_attempted_at=_last_attempted_at(item),
            next_attempt_at=item.next_attempt_at,
            last_error=item.last_error,
            delivery_mode=item.delivery_mode,
            synced_at=item.synced_at,
            created_at=item.created_at or item.updated_at or item.synced_at,
            updated_at=item.updated_at or item.created_at or item.synced_at,
        )
        for item in items
    ]


@router.post("/flush", response_model=SyncFlushRead)
def flush_sync_backlog(
    limit: int = Query(default=100, ge=1, le=500),
    container: AppContainer = Depends(get_container),
) -> SyncFlushRead:
    result = container.sync.flush_pending(limit=limit)
    return SyncFlushRead(
        attempted=result.attempted,
        synced=result.synced,
        failed=result.failed,
        deferred=result.deferred,
        pending=result.pending,
        remote_available=container.sync.remote_available(),
        target=dict(container.sync.target),
        next_attempt_at=result.next_attempt_at,
    )


def _last_attempted_at(item) -> object | None:
    if item.payload and isinstance(item.payload.get("delivery"), dict):
        return item.payload["delivery"].get("last_attempt_at") or item.updated_at
    return item.updated_at
