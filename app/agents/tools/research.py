"""
Persistance des recherches
"""

import asyncio

from app.agents.deps import ChatDeps
from app.services.database import create_research, update_sql


async def persist_new_research(deps: ChatDeps, isSemantic: bool, intention: str = None) -> int:
    """
    Crée une nouvelle ligne `research` avec la dernière requête SQL exécutée.
    """
    if not deps.last_sql:
        raise ValueError("Aucune requête SQL à persister (deps.last_sql vide).")
    research_id = await asyncio.to_thread(create_research, deps.user_id, deps.last_sql, isSemantic)
    deps.events.research(research_id=research_id, sql=deps.last_sql, intention=intention)
    return research_id


async def persist_affinage(deps: ChatDeps, intention: str = None) -> int:
    """
    Met à jour la requête SQL de la recherche existante (affinage).
    """
    if not deps.last_sql:
        raise ValueError("Aucune requête SQL à persister (deps.last_sql vide).")
    last_id = deps.historique[-2]["id"] if len(deps.historique) >= 2 else deps.last_message_id
    research_id = await asyncio.to_thread(update_sql, last_id, deps.last_sql, deps.research_id)
    deps.events.research(research_id=research_id, sql=deps.last_sql, intention=intention)
    return research_id
