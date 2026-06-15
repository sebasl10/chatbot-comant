from fastapi import APIRouter
from app.models.chat import NameRequest
from app.services.conversation_name import create_name

router = APIRouter(prefix="/name", tags=["name"])

@router.post("/create")
async def create_conversation_name(request: NameRequest):
    name = await create_name(request.conversation_id, request.historique)
    return {"name": name}