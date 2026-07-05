"""Tool de validation du vocabulaire métier (LangChain).

L'agent identifie les entités nommées du message puis appelle ce tool pour les
valider contre les valeurs réelles en base (fuzzy match via ``link_entities``).
"""
import asyncio

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from pydantic import BaseModel

from app.services.entity_cache import link_entities, CACHEABLE_COLUMNS

ENTITY_TYPES = ", ".join(sorted(CACHEABLE_COLUMNS.keys()))


class Entity(BaseModel):
    type: str  # un des ENTITY_TYPES
    value: str


@tool
async def validate_entities(entities: list[Entity], config: RunnableConfig) -> dict:
    """Valide des entités nommées {type, value} contre le vocabulaire réel de la base.

    `type` doit être l'un de : branch_dev, branch_release, branch_travail, client,
    component, product, project, tag, user. Renvoie chaque entité avec un statut
    (ok / suggestion / unknown). Si `unknown` ou `suggestion`, demande une
    clarification à l'utilisateur avant de générer le SQL.
    """
    raw = [e.model_dump() for e in entities]
    linked = await asyncio.to_thread(link_entities, raw)
    return {"entities": linked}
