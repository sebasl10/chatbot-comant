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
    Renvoie la requête SQL construite, les synonymes utilisés et le count.
    
    Args:
        query: Message exact envoyé par l'utilisateur, sans modification, sans reformulation, sans ajout de texte
    
    Returns:
        dict avec les clés:
        - sql_query: requête SQL au format SELECT t.id, t.summary, t.description FROM ticket t WHERE t.id IN (<ids>)
        - synonyms: liste de tous les termes utilisés (query + synonymes)
        - count: nombre de tickets trouvés
    """
    print("[TOOL CALL] semantic_ticket_search")
    print(f"Query: {query}")
    
    result = await asyncio.to_thread(vs.query_tickets, query)
    ticket_ids = result['ticket_ids']
    if ticket_ids:
        ids_str = ", ".join(str(tid) for tid in ticket_ids)
        sql_query = f"SELECT t.id, t.summary, t.description FROM ticket t WHERE t.id IN ({ids_str})"
    else:
        sql_query = "SELECT t.id, t.summary, t.description FROM ticket t WHERE t.id IN ()"
        
    print(f"[SQL RESULT] {sql_query}")
    
    return {
        "sql_query": sql_query,
        "synonyms": result["synonyms"],
        "count": result["count"]
    }


async def get_vocabulary_for_term(ctx: RunContext[ChatDeps], term: str) -> dict:
    """
    Récupère le vocabulaire (synonymes) associé à un terme donné avec ses métadonnées.
    Utilisé pour répondre à des questions comme :
    - "Quel est le vocabulaire que tu connais pour X ?"
    - "Quels sont les termes liés à X ?"
    - "Qui a ajouté le terme X ?"
    - "Qui t'a dit que X doit être inclus ?"
    
    Args:
        term: Le terme de base pour lequel on veut récupérer les synonymes
    
    Returns:
        dict avec les clés:
        - base_term: le terme de base
        - synonyms: liste des synonymes/termes liés
        - metadata: dict avec username, date, user_id, etc. (ou None)
        - count: nombre de synonymes trouvés
    """
    print("[TOOL CALL] get_vocabulary_for_term")
    print(f"Term: {term}")
    
    result = await asyncio.to_thread(vs.get_vocabulary_for_term, term)
    print(f"[RESULTS] Vocabulaire pour '{term}': {result}")
    
    return result


async def remove_term_from_vocabulary(ctx: RunContext[ChatDeps], term: str, base_term: str) -> dict:
    """
    Supprime un terme spécifique du vocabulaire associé à un terme de base.
    Utilisé pour répondre à des questions comme :
    - "supprime X du vocabulaire lié à Y"
    - "X ne doit pas être lié à Y"
    
    Args:
        term: Le terme à supprimer (ex: "lent")
        base_term: Le terme de base dont on veut supprimer le synonyme (ex: "performance")
    
    Returns:
        dict avec les clés:
        - success: bool indiquant si la suppression a réussi
        - message: message de confirmation ou d'erreur
        - base_term: le terme de base
        - removed_term: le terme supprimé
    """
    print("[TOOL CALL] remove_term_from_vocabulary")
    print(f"Term to remove: {term}, Base term: {base_term}")
    
    result = await asyncio.to_thread(vs.remove_term_from_vocabulary, term, base_term)
    print(f"[RESULTS] Suppression de '{term}' du vocabulaire de '{base_term}': {result}")
    
    return result
