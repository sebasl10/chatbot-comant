from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    ollama_url: str
    ollama_url_embedding: str
    model_ia: str
    model_ia_embedding: str
    cors_origins : list[str]

    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str

    ollama_openai_base_url: str = "http://localhost:11434/v1"
    chroma_http_url: str = "http://localhost:8001"

    class Config:
        env_file = ".env" 

settings = Settings()