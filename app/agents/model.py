from functools import lru_cache
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from app.config import settings

@lru_cache(maxsize=1)
def get_agent_model() -> OpenAIChatModel:
    """
    Retourne le modèle partagé par tous les agents (mis en cache).
    """
    model_name = settings.model_ia
    provider = OpenAIProvider(
        base_url=settings.ollama_openai_base_url,
        api_key="ollama",
    )
    return OpenAIChatModel(model_name, provider=provider)
