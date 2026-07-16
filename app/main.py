import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import logfire

from app.config import settings
from app.models.chat import ChatRequest, NameRequest
from app.agents.deps import ChatDeps
from app.agents.orchestrator import run_chat_stream
from app.services.database import get_username
from app.services.conversation_name import create_name
from app.services.finetuning_couples import export_finetuning_service

app = FastAPI(title="LLM API Comant", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logfire.configure()
logfire.instrument_system_metrics()
logfire.instrument_pydantic_ai()
logfire.instrument_fastapi(app)


@app.get("/")
def read_root():
    return {"message": "Bienvenue dans ton application FastAPI !"}

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/chat/stream", tags=["chat"])
async def chat_stream(request: ChatRequest):
    username = await asyncio.to_thread(get_username, request.user_id)
    deps = ChatDeps(
        user_id=request.user_id,
        research_id=request.research_id,
        last_message_id=request.last_message_id,
        historique=request.historique,
        username=username,
    )
    return StreamingResponse(
        run_chat_stream(request.message, deps),
        media_type="text/plain",
    )


@app.post("/name/create", tags=["name"])
async def create_conversation_name(request: NameRequest):
    name = await create_name(request.conversation_id, request.historique)
    return {"name": name}


@app.get("/admin/export-finetuning", tags=["admin"])
def export_finetuning():
    export_finetuning_service()
