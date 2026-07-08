import asyncio

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.config import settings
from app.models.chat import ChatRequest
from app.agents.deps import ChatDeps
from app.agents.orchestrator import run_chat_stream
from app.services.database import get_username
from app.services.router import handle_stream  # pipeline legacy (agent_mode = False)

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/stream")
async def chat_stream(request: ChatRequest):
    if settings.agent_mode:
        username = await asyncio.to_thread(get_username, request.user_id)
        deps = ChatDeps(
            user_id=request.user_id,
            research_id=request.research_id,
            last_message_id=request.last_message_id,
            historique=request.historique,
            username=username,
            message=request.message
        )
        return StreamingResponse(
            run_chat_stream(request.message, deps),
            media_type="text/plain",
        )

    # Ancien pipeline (repli / A/B).
    return StreamingResponse(
        handle_stream(
            request.message, request.user_id, request.historique,
            request.last_message_id, request.intention, request.research_id,
        ),
        media_type="text/plain",
    )
