from pydantic import BaseModel
from app.config import settings

class ChatRequest(BaseModel):
    message: str
    model: str = settings.model_ia
    user_id: int
    historique: list[dict] = []
    last_message_id: int
    intention: str
    research_id: int

class NameRequest(BaseModel):
    historique: list
    conversation_id: int
    
class MemoryRequest(BaseModel):
    id: str | None = None
    content: str | None = None
    base_term: str | None = None
    type: str | None = None
    scope: str | None = None
    user_id: int | None = None
    
