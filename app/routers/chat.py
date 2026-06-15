from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from app.models.chat import ChatRequest
from app.services.router import handle_stream

router = APIRouter(prefix="/chat", tags=["chat"])

@router.post("/stream")
async def chat_stream(request: ChatRequest):
    return StreamingResponse(
        handle_stream(request.message, request.user_id, request.historique, request.last_message_id, request.intention, request.research_id), 
        media_type="text/plain"
    )