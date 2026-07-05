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
    # Endpoint OpenAI-compatible d'Ollama, utilisé par Pydantic AI pour le
    # tool calling natif. Défaut dérivé d'ollama_base_url si non fourni.
    ollama_openai_base_url: str = "http://localhost:11434/v1"
    # Modèle utilisé par les agents (function calling). Vide => fallback model_ia.
    model_ia_tools: str = ""
    # Répertoire persistant de la base vectorielle Chroma.
    chroma_path: str = "app/chroma_db"
    # Bascule superviseur agent (True) vs ancien pipeline handle_stream (False).
    # Permet un A/B et un repli immédiat pendant la transition.
    agent_mode: bool = True

    class Config:
        env_file = ".env" # Surcharge via .env

settings = Settings()