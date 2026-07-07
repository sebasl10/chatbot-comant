"""Tool de validation du vocabulaire métier.

L'agent identifie lui-même les entités nommées du message (projet, utilisateur,
client, composant, produit, tag, branches) puis appelle ce tool pour les valider
contre les valeurs réelles présentes en base (fuzzy match via rapidfuzz).

Réutilise ``link_entities`` de ``app/services/entity_cache.py``. Chaque entité
reçoit un statut :
- ``ok``         : la valeur existe (``resolved`` = valeur canonique)
- ``suggestion`` : valeur proche trouvée (``suggestion`` = proposition)
- ``unknown``    : aucune correspondance
"""
import asyncio

from pydantic import BaseModel
from pydantic_ai import RunContext

from app.agents.deps import ChatDeps
from app.services.entity_cache import link_entities, CACHEABLE_COLUMNS

# Types d'entités reconnus (clés de CACHEABLE_COLUMNS) — exposés dans la docstring
# pour guider le modèle.
ENTITY_TYPES = ", ".join(sorted(CACHEABLE_COLUMNS.keys()))


class Entity(BaseModel):
    type: str  # un des ENTITY_TYPES
    value: str


async def validate_entities(ctx: RunContext[ChatDeps], entities: list[Entity]) -> dict:
    """Valide des entités nommées contre le vocabulaire réel de la base.

    `type` doit être l'un de : {types}. Renvoie chaque entité avec son statut
    (ok / suggestion / unknown). Si des entités sont `unknown` ou `suggestion`,
    l'agent doit demander une clarification à l'utilisateur avant de générer le SQL.
    """
    raw = [e.model_dump() for e in entities]
    linked = await asyncio.to_thread(link_entities, raw)
    return {"entities": linked}


# Injecte la liste des types dans la docstring vue par le modèle.
validate_entities.__doc__ = validate_entities.__doc__.format(types=ENTITY_TYPES)
