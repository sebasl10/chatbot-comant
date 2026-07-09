"""
Persistance des recherches 

Ces helpers ne sont PAS exposés au LLM : la création/mise à jour d'une recherche
doit se produire exactement une fois, pilotée par la couche de délégation après
qu'un agent spécialiste a produit une requête SQL valide (mémorisée dans
``deps.last_sql`` par le tool ``run_sql``).

Ils émettent l'événement ``research`` (research_id + sql) que le front consomme
pour rediriger vers l'onglet Recherche et afficher les résultats.
"""
import asyncio
from app.agents.deps import ChatDeps
from app.services.database import create_research, update_sql

async def persist_new_research(deps: ChatDeps) -> int:
    """
    Crée une nouvelle ligne `research` avec la dernière requête SQL exécutée.
    """
    if not deps.last_sql:
        raise ValueError("Aucune requête SQL à persister (deps.last_sql vide).")
    research_id = await asyncio.to_thread(create_research, deps.user_id, deps.last_sql)
    deps.events.research(research_id=research_id, sql=deps.last_sql)
    return research_id


async def persist_affinage(deps: ChatDeps) -> int:
    """
    Met à jour la requête SQL de la recherche existante (affinage).
    """
    if not deps.last_sql:
        raise ValueError("Aucune requête SQL à persister (deps.last_sql vide).")
    last_id = deps.historique[-2]["id"] if len(deps.historique) >= 2 else deps.last_message_id
    research_id = await asyncio.to_thread(update_sql, last_id, deps.last_sql, deps.research_id)
    deps.events.research(research_id=research_id, sql=deps.last_sql)
    return research_id
