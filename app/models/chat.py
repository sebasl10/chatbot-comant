from pydantic import BaseModel
from app.config import settings

class ChatRequest(BaseModel):
    message: str
    model: str = settings.model_ia
    user_id: int
    historique: list[dict] = []
    last_message_id: int
    research_id: int

class NameRequest(BaseModel):
    historique: list
    conversation_id: int
    
class MemoryRequest(BaseModel):
    id: str | None = None
    content: str | None = None
    base_term: str | None = None
    target_agent: str | None = None
    kind: str | None = None
    user_id: int | None = None

class EmbeddingRequest(BaseModel):
    ticket_id: int
    
