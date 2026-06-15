from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    ollama_url: str 
    model_ia: str 
    cors_origins : list[str]

    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str

    class Config:
        env_file = ".env" # Surcharge via .env

settings = Settings()