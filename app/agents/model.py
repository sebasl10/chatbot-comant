from functools import lru_cache

from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings

from app.config import settings

DETERMINISTIC_SETTINGS = ModelSettings(temperature=0.0)
"""Sortie contrainte : SQL, routage vers un outil, classification. Aucune créativité utile."""

FACTUAL_SETTINGS = ModelSettings(temperature=0.2)
"""Reformulation ancrée dans des données : requêtes sémantiques, règles mémorisées."""

CONVERSATIONAL_SETTINGS = ModelSettings(temperature=0.6)
"""Rédaction libre adressée à l'utilisateur : salutations, aide, refus."""


@lru_cache(maxsize=1)
def get_agent_model() -> OpenAIChatModel:
    """
    Retourne le modèle partagé par tous les agents (mis en cache).

    La température n'est pas fixée ici : chaque agent passe son propre profil
    via ``model_settings``.
    """
    model_name = settings.model_ia
    provider = OpenAIProvider(
        base_url=settings.ollama_openai_base_url,
        api_key="ollama",
    )
    return OpenAIChatModel(model_name, provider=provider)
