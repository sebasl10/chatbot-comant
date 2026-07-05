"""Tool de recherche sémantique de tickets (backed Chroma).

Le vecteur de requête est calculé avec ``embedding.get_embedding`` (même modèle
+ même préfixe d'instruction qu'avant, pour la parité), puis la recherche des
plus proches voisins est déléguée à la collection Chroma ``tickets``.

Signature inchangée depuis la Phase 1 : seul le backend a changé (MySQL/cosine
en Python → Chroma).
"""
import asyncio

from pydantic_ai import RunContext

from app.agents.deps import ChatDeps
from app.services.embedding import get_embedding
from app.services import vectorstore as vs

_DEFAULT_THRESHOLD = 0.5


async def semantic_ticket_search(
    ctx: RunContext[ChatDeps], query: str, threshold: float = _DEFAULT_THRESHOLD
) -> dict:
    """Recherche des tickets sémantiquement proches de `query` (sujet/thème).

    `threshold` est le seuil de similarité cosinus (0.5 par défaut). Renvoie les
    `ticket_id` triés par pertinence décroissante. À utiliser pour les recherches
    par thème ("tickets qui parlent de cinématique") plutôt que par filtres exacts.
    """
    query_emb = (await asyncio.to_thread(get_embedding, query))[0]
    ids = await asyncio.to_thread(vs.query_tickets, query_emb, threshold)
    return {"ticket_ids": ids, "count": len(ids)}
