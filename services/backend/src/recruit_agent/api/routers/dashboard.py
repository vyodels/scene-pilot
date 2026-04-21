from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from recruit_agent.api.deps import get_container, get_session
from recruit_agent.schemas.domain import DashboardRead
from recruit_agent.services.container import AppContainer

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardRead)
def get_dashboard(
    container: AppContainer = Depends(get_container),
    session: Session = Depends(get_session),
) -> DashboardRead:
    return container.dashboard.build_dashboard(session, queue_depth=container.scheduler.queue.size())

