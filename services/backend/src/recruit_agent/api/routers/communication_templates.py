from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from recruit_agent.api.deps import get_session
from recruit_agent.schemas import (
    CommunicationTemplateRead,
    CommunicationTemplateRenderRead,
    CommunicationTemplateRenderRequest,
)
from recruit_agent.services.communication_templates import list_communication_templates, render_communication_template


router = APIRouter(prefix="/api/communication-templates", tags=["communication-templates"])


@router.get("", response_model=list[CommunicationTemplateRead])
def get_communication_templates() -> list[CommunicationTemplateRead]:
    return [CommunicationTemplateRead.model_validate(item) for item in list_communication_templates()]


@router.post("/{template_id}/render", response_model=CommunicationTemplateRenderRead)
def render_template(
    template_id: str,
    payload: CommunicationTemplateRenderRequest,
    session: Session = Depends(get_session),
) -> CommunicationTemplateRenderRead:
    rendered = render_communication_template(
        session,
        template_id=template_id,
        application_id=payload.application_id,
        variables=payload.variables,
    )
    if rendered is None:
        raise HTTPException(status_code=404, detail="Communication template or application not found")
    return CommunicationTemplateRenderRead.model_validate(rendered)
