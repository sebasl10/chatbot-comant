"""Factory du modèle Pydantic AI branché sur Ollama.

Ollama expose un endpoint compatible OpenAI (`/v1`) qui supporte le tool
calling natif pour les modèles qui l'implémentent (Mistral/ministral, Qwen…).
On l'utilise via l'``OpenAIChatModel`` de Pydantic AI plutôt que l'ancien
``/api/generate`` (qui n'a ni messages structurés ni tools).

L'ancien client ``app/services/ollama.py`` reste utilisé pour les embeddings
et le code legacy ; toute la partie *chat/agents* passe désormais par ici.
"""
from functools import lru_cache

from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from app.config import settings


@lru_cache(maxsize=1)
def get_agent_model() -> OpenAIChatModel:
    """Retourne le modèle partagé par tous les agents (mis en cache).

    - ``base_url`` pointe sur l'endpoint OpenAI-compatible d'Ollama.
    - ``api_key`` est factice : Ollama ne l'exige pas mais le client OpenAI
      refuse une valeur vide.
    - Le nom du modèle vient de ``model_ia_tools`` (fallback ``model_ia``).
    """
    model_name = settings.model_ia_tools or settings.model_ia
    provider = OpenAIProvider(
        base_url=settings.ollama_openai_base_url,
        api_key="ollama",
    )
    return OpenAIChatModel(model_name, provider=provider)
