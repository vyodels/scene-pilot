from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from scene_pilot.api.deps import get_session
from scene_pilot.repositories import MetricsRepository
from scene_pilot.schemas import MetricsSummary

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


@router.get("", response_model=MetricsSummary)
def get_metrics(session: Session = Depends(get_session)) -> MetricsSummary:
    return MetricsRepository(session).summary()

