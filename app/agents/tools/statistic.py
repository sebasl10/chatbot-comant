"""
Persistance des statistiques
"""

import asyncio

from app.agents.deps import ChatDeps
from app.services.database import create_statistic

async def persist_statistic(deps: ChatDeps) -> int:
    """
    Crée une nouvelle ligne `statistics` avec la dernière requête SQL (statistiques) exécutée.
    """
    if not deps.last_stats_sql:
        raise ValueError("Aucune requête SQL (stats) à persister (deps.last_stats_sql vide).")
    statistic_id = await asyncio.to_thread(create_statistic, deps.user_id, deps.last_stats_sql)
    deps.events.research(research_id=statistic_id)
    return statistic_id