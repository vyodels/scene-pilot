from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from recruit_agent.agents.assistant import AssistantAdapter
from recruit_agent.assistant.stream import format_sse_event


class CreateConversationRequest(BaseModel):
    user_id: str
    title: str | None = None


class TurnRequest(BaseModel):
    message: str


def build_router(agent: AssistantAdapter) -> APIRouter:
    router = APIRouter(prefix="/api/assistant", tags=["assistant"])

    @router.post("/conversations")
    def create_conversation(payload: CreateConversationRequest) -> dict[str, Any]:
        conversation = agent.create_conversation(user_id=payload.user_id, title=payload.title)
        return {
            "conversation_id": conversation.conversation_id,
            "user_id": conversation.user_id,
            "title": conversation.title,
        }

    @router.get("/conversations")
    def list_conversations(user_id: str | None = None) -> list[dict[str, Any]]:
        return [
            {
                "conversation_id": conversation.conversation_id,
                "user_id": conversation.user_id,
                "title": conversation.title,
                "status": conversation.status,
            }
            for conversation in agent.list_conversations(user_id=user_id)
        ]

    @router.get("/conversations/{conversation_id}")
    def get_conversation(conversation_id: str) -> dict[str, Any]:
        conversation = agent.get_conversation(conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="conversation not found")
        return {
            "conversation_id": conversation.conversation_id,
            "user_id": conversation.user_id,
            "title": conversation.title,
            "status": conversation.status,
        }

    @router.delete("/conversations/{conversation_id}")
    def delete_conversation(conversation_id: str) -> dict[str, Any]:
        return {"deleted": agent.delete_conversation(conversation_id)}

    @router.post("/conversations/{conversation_id}/turn")
    def create_turn(conversation_id: str, payload: TurnRequest) -> StreamingResponse:
        def _stream():
            for event, data in agent.run_turn_stream(conversation_id, payload.message):
                yield format_sse_event(event, data)

        return StreamingResponse(_stream(), media_type="text/event-stream")

    @router.post("/conversations/{conversation_id}/confirm")
    def confirm_turn(conversation_id: str) -> dict[str, Any]:
        return agent.confirm_turn(conversation_id)

    @router.post("/conversations/{conversation_id}/cancel")
    def cancel_turn(conversation_id: str) -> dict[str, Any]:
        return agent.cancel_turn(conversation_id)

    return router
