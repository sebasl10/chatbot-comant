"""Factory du modèle LangChain branché sur Ollama.

Variante LangGraph : on utilise ``ChatOllama`` (``langchain-ollama``), qui parle
à l'API native d'Ollama (``/api/chat``) et supporte le **tool calling** via
``bind_tools`` (fait automatiquement par ``create_agent``).

Équivalent LangChain du ``OpenAIChatModel`` de la branche Pydantic AI.
Le client Ollama (embeddings, legacy) reste dans ``app/services/ollama.py``.
"""
from functools import lru_cache

from langchain_ollama import ChatOllama

from app.config import settings


@lru_cache(maxsize=1)
def get_agent_model() -> ChatOllama:
    """Modèle partagé par tous les agents (mis en cache).

    - ``base_url`` : hôte Ollama (sans le suffixe ``/v1`` — ChatOllama utilise
      l'API native).
    - Modèle : ``model_ia_tools`` (fallback ``model_ia``), doit supporter le
      function calling (Mistral/ministral, Qwen).
    - ``temperature=0`` pour des appels d'outils déterministes.
    """
    model_name = settings.model_ia_tools or settings.model_ia
    return ChatOllama(
        model=model_name,
        base_url=settings.ollama_base_url,
        temperature=0,
    )
