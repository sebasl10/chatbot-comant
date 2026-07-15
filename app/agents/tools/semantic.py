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


async def get_vocabulary_for_term(ctx: RunContext[ChatDeps], term: str) -> dict:
    """
    Récupère le vocabulaire (synonymes) associé à un terme donné.
    Utilisé pour répondre à des questions comme "Quel est le vocabulaire que tu connais pour X ?"
    ou "Quels sont les termes liés à X ?".
    
    Args:
        term: Le terme de base pour lequel on veut récupérer les synonymes
    
    Returns:
        dict avec les clés:
        - term: le terme de base
        - synonyms: liste des synonymes/termes liés
        - count: nombre de synonymes trouvés
    """
    print("[TOOL CALL] get_vocabulary_for_term")
    print(f"Term: {term}")
    
    synonyms = await asyncio.to_thread(vs.get_synonyms_for_term, term)
    
    return {"term": term, "synonyms": synonyms, "count": len(synonyms)}
