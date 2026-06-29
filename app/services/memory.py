from mem0 import Memory, MemoryClient
from app.config import settings
from typing import Optional, Union
import logging
import warnings

warnings.filterwarnings("ignore", message="Multiple active PostHog clients detected")

_memory: Optional[Memory] = None

def get_memory() -> Memory:
    global _memory
    if _memory is None:
        config = {
            "llm": {
                "provider": "ollama",
                "config": {
                    "model": settings.model_ia,
                    "ollama_base_url": settings.ollama_base_url,
                }
            },
            "embedder": {
                "provider": "ollama",
                "config": {
                    "model": settings.model_ia_embedding,
                    "ollama_base_url": settings.ollama_base_url,
                }
            },
            "vector_store": {
                "provider": "qdrant",
                "config": {
                    "collection_name": "comant_memory",
                    "path": "./mem0_db",
                    "embedding_model_dims": 2560
                }
            }
        }
        _memory = Memory.from_config(config)
    return _memory


def close_memory():
    """Fermer explicitement la mémoire pour éviter les erreurs de cleanup Qdrant"""
    global _memory
    if _memory is not None:
        try:
            if hasattr(_memory, 'vector_store') and _memory.vector_store:
                if hasattr(_memory.vector_store, 'client') and _memory.vector_store.client:
                    _memory.vector_store.client.close()
        except Exception:
            pass
        _memory = None


def add_memory(content: str, user_id: Union[str, int]) -> None:
    get_memory().add(content, user_id=str(user_id))


def search_memory(query: str, user_id: Union[str, int], limit: int = 5) -> list[dict]:
    results = get_memory().search(query, filters={"user_id": str(user_id)}, limit=limit)
    return results.get("results", [])

def get_all_memories(user_id: Union[str, int] = None, limit: int = None) -> list[dict]:
    memory = get_memory()
    if user_id:
        results = memory.get_all(filters={"user_id": str(user_id)}, limit=limit)
    else:
        results = memory.get_all(limit=limit)
    
    memories = []
    for result in results.get("results", []):
        memories.append(result['memory'])
    return memories

def extract_search_thread(history: list[dict], user_id: str) -> None:
    """
    Remonte l'historique pour trouver la recherche initiale + tous les affinages
    consécutifs jusqu'au message actuel, puis sauvegarde dans mem0.
    S'arrête dès qu'une recherche initiale est trouvée.
    """
    intents_recherche = {"recherche", "recherche_semantique", "recherche_hybride"}
    intents_affinage = {"affinage"}
    intents_valides = intents_recherche | intents_affinage | {None}

    thread_user_messages = []
    found_recherche = False 

    for msg in reversed(history):
        intention = msg.get("intention")
        if intention in intents_valides and not found_recherche:
            thread_user_messages.insert(0, msg)
            if intention in intents_recherche:
                found_recherche = True
                break

    if not thread_user_messages:
        return
    
    messages = []
    for msg in thread_user_messages:
        if msg["role"] == "user":
            messages.append({"role": msg["role"], "content": msg["content"]})
        else:
            messages.append({"role": msg["role"], "content": msg["sql"]})
    print(messages)
    add_memory(messages, user_id)


def delete_memories(user_id: Union[int, str]):
    memory = get_memory()
    user_id_str = str(user_id)
    memory.delete_all(user_id=user_id_str)