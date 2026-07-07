from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    ollama_base_url: str
    ollama_url: str 
    ollama_url_embedding: str
    lmstudio_url: str 
    model_ia: str
    model_ia_lmstudio: str
    model_ia_embedding: str
    cors_origins : list[str]

    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str

    # ── Architecture agent (Pydantic AI + Ollama tool calling) ──────────────
    # Endpoint OpenAI-compatible d'Ollama, utilisé par Pydantic AI pour le tool calling natif
    ollama_openai_base_url: str = "http://localhost:11434/v1"
    chroma_path: str = "app/chroma_db"
    chroma_http_url: str = "http://localhost:8001"
    agent_mode: bool = True

    class Config:
        env_file = ".env" # Surcharge via .env

settings = Settings()