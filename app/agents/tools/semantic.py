"""
Tool de recherche sémantique de tickets (backed Chroma).
"""

import asyncio
from pydantic_ai import RunContext
from app.agents.deps import ChatDeps
from app.services.embedding import get_embedding
from app.services import vectorstore as vs

_DEFAULT_THRESHOLD = 0.5

async def semantic_ticket_search(ctx: RunContext[ChatDeps], query: str) -> dict:
    """
    Recherche des tickets sémantiquement proches de `query` (sujet/thème).
    Renvoie les `ticket_id` triés par pertinence décroissante.
    
    Args:
        query: Message exact envoyé par l'utilisateur, sans modification, sans reformulation, sans ajout de texte
    """
    query_emb = (await asyncio.to_thread(get_embedding, query))[0]
    ids = await asyncio.to_thread(vs.query_tickets, query_emb)
    return {"ticket_ids": ids, "count": len(ids)}
