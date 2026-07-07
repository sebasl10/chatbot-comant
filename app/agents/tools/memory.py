"""Tools mémoire (souvenirs / corrections), backed Chroma.

Stockage dans la collection Chroma ``memories`` (filtrage par métadonnées
``type``/``scope``/``user_id`` + recherche sémantique). Signatures inchangées
depuis la Phase 1 : seul le backend a changé (Markdown → Chroma).

Types de mémoire : correction_sql, expand_vocabulary (global), exclude_ticket,
other_correction.
"""
import asyncio

from pydantic_ai import RunContext

from app.agents.deps import ChatDeps
from app.services import vectorstore as vs

VALID_MEMORY_TYPES = ("correction_sql", "expand_vocabulary", "exclude_ticket", "other_correction")


async def get_memory(ctx: RunContext[ChatDeps], type: str, query: str | None = None) -> str:
    """Récupère les souvenirs mémorisés de l'utilisateur pour un `type` donné.

    Types valides : correction_sql (règles de correction SQL), expand_vocabulary
    (synonymes/vocabulaire, global), exclude_ticket (tickets à exclure),
    other_correction. Si `query` est fourni, renvoie les souvenirs les plus
    pertinents sémantiquement ; sinon tous ceux du type. Vide si aucun.
    """
    if type not in VALID_MEMORY_TYPES:
        return ""
    return await asyncio.to_thread(vs.get_memories_text, type, ctx.deps.user_id, query)


async def save_memory(ctx: RunContext[ChatDeps], type: str, content: str) -> dict:
    """Enregistre un nouveau souvenir de `type` donné pour l'utilisateur.

    À utiliser quand l'utilisateur corrige le comportement du chatbot ou ajoute
    une règle/synonyme à retenir. Types valides : correction_sql, expand_vocabulary,
    exclude_ticket, other_correction.
    """
    if type not in VALID_MEMORY_TYPES:
        return {"ok": False, "error": f"type invalide: {type}"}
    await asyncio.to_thread(
        vs.add_memory, type, content, ctx.deps.user_id, ctx.deps.username
    )
    ctx.deps.events.correction(type=type, memory=content)
    return {"ok": True, "type": type}
