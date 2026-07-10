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
    Utilise les synonymes expand_vocabulary si disponibles.
    Renvoie les `ticket_id` triés par pertinence décroissante.
    
    Args:
        query: Message exact envoyé par l'utilisateur, sans modification, sans reformulation, sans ajout de texte
    """
    print("[TOOL CALL] semantic_ticket_search")
    print(f"Query: {query}")
    
    # Récupérer les synonymes pour cette requête
    synonyms = await asyncio.to_thread(vs.get_synonyms_for_term, query)
    print(f"[SYNONYMS] Synonymes trouvés pour '{query}': {synonyms}")
    
    # Utiliser la nouvelle méthode avec synonymes
    ids = await asyncio.to_thread(vs.query_tickets_with_synonyms, query)
    print(f"[RESULTS] Ticket IDs trouvés: {ids}")
    
    return {"ticket_ids": ids, "count": len(ids)}
