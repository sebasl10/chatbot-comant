"""
Tool de validation du vocabulaire métier.

L'agent identifie lui-même les entités nommées du message (projet, utilisateur,
client, composant, produit, tag, branches) puis appelle ce tool pour les valider
contre les valeurs réelles présentes en base (fuzzy match via rapidfuzz).
"""

import asyncio

from pydantic import BaseModel
from pydantic_ai import RunContext

from app.agents.deps import ChatDeps
from app.services.entity_cache import CACHEABLE_COLUMNS, link_entities

ENTITY_TYPES = ", ".join(sorted(CACHEABLE_COLUMNS.keys()))


class Entity(BaseModel):
    type: str
    value: str


async def validate_entities(ctx: RunContext[ChatDeps], entities: list[Entity]) -> dict:
    """
    Valide des entités nommées contre le vocabulaire réel de la base.

    `type` doit être l'un de : {types}. Renvoie chaque entité avec son statut :
    - `ok` : la valeur existe, utilise `resolved` dans le SQL ;
    - `suggestion` / `unknown` : demande une clarification à l'utilisateur AVANT de
      générer le SQL ;
    - `ignored` : la valeur n'avait pas à être envoyée ici (voir `reason`) ; ne
      demande aucune clarification et poursuis normalement.

    N'envoie QUE des noms propres du métier (un code projet, un trigramme
    d'utilisateur, un nom de client, de composant, de produit, de tag, de branche).
    N'envoie JAMAIS :
    - une PÉRIODE : "2026", "mars 2026", "ce mois-ci", "les 30 derniers jours", car c'est
      un filtre de date (`YEAR(...) = 2026`), pas une entité. Une année ressemble à
      tous les codes projet qui la contiennent ("2026" → "3df_2026") : l'envoyer ici
      déclenche une suggestion absurde ;
    - une valeur de référence (`ticket.type`, `ticket.status`, `project.type`...) : elles
      sont déjà listées dans ton prompt, utilise-les telles quelles ;
    - un thème, un mot-clé de recherche libre ou un nom de colonne.

    Args:
        entities: Liste d'instances de la classe Entity avec 'type' le type de l'entité et 'value' sa valeur
    """
    raw = [e.model_dump() for e in entities]
    linked = await asyncio.to_thread(link_entities, raw)
    
    ctx.deps.awaiting_entity_clarification = any(
        e["status"] in ("suggestion", "unknown") for e in linked
    )
    return {"entities": linked}


# Injecte la liste des types dans la docstring vue par le modèle.
validate_entities.__doc__ = validate_entities.__doc__.format(types=ENTITY_TYPES)
