"""Tools mémoire (souvenirs / corrections) — LangChain, backed Chroma.

Stockage dans la collection Chroma ``memories`` (filtrage par métadonnées
type/scope/user_id + recherche sémantique). Types : correction_sql,
expand_vocabulary (global), exclude_ticket, other_correction.
"""
import asyncio

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.agents.context import deps_from_config
from app.services import vectorstore as vs

VALID_MEMORY_TYPES = ("correction_sql", "expand_vocabulary", "exclude_ticket", "other_correction")


@tool
async def get_memory(type: str, config: RunnableConfig, query: str | None = None) -> str:
    """Récupère les souvenirs mémorisés de l'utilisateur pour un `type` donné.

    Types valides : correction_sql (règles de correction SQL), expand_vocabulary
    (synonymes/vocabulaire, global), exclude_ticket (tickets à exclure),
    other_correction. Si `query` est fourni, renvoie les souvenirs les plus
    pertinents sémantiquement ; sinon tous ceux du type. Vide si aucun.
    """
    if type not in VALID_MEMORY_TYPES:
        return ""
    deps = deps_from_config(config)
    return await asyncio.to_thread(vs.get_memories_text, type, deps.user_id, query)


@tool
async def save_memory(type: str, content: str, config: RunnableConfig) -> dict:
    """Enregistre un nouveau souvenir de `type` donné pour l'utilisateur.

    À utiliser quand l'utilisateur corrige le comportement du chatbot ou ajoute
    une règle/synonyme à retenir. Types valides : correction_sql, expand_vocabulary,
    exclude_ticket, other_correction.
    """
    if type not in VALID_MEMORY_TYPES:
        return {"ok": False, "error": f"type invalide: {type}"}
    deps = deps_from_config(config)
    await asyncio.to_thread(vs.add_memory, type, content, deps.user_id, deps.username)
    deps.events.correction(type=type, memory=content)
    return {"ok": True, "type": type}
