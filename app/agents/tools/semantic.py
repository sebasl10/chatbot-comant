"""
Tool de recherche sémantique de tickets (backed Chroma).
"""

import asyncio
from pydantic_ai import RunContext
from app.agents.deps import ChatDeps
from app.services import vectorstore as vs

async def semantic_ticket_search(ctx: RunContext[ChatDeps], query: str) -> dict:
    """
    Recherche des tickets sémantiquement proches de `query` (sujet/thème).
    Renvoie les `ticket_id` triés par pertinence décroissante ainsi que les synonymes utilisés.
    
    Args:
        query: Message exact envoyé par l'utilisateur, sans modification, sans reformulation, sans ajout de texte
    
    Returns:
        dict avec les clés:
        - ticket_ids: liste des IDs de tickets trouvés
        - synonyms: liste de tous les termes utilisés (query + synonymes)
        - count: nombre de tickets trouvés
    """
    print("[TOOL CALL] semantic_ticket_search")
    print(f"Query: {query}")
    
    result = await asyncio.to_thread(vs.query_tickets_with_synonyms, query)
    print(f"[RESULTS] Ticket IDs trouvés: {result['ticket_ids']}")
    
    return result
