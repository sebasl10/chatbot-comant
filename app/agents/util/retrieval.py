"""Condensation de requête pour la récupération de souvenirs.

Embedder directement un message comme « oui » ou « celui-là » ne retrouve
aucun souvenir pertinent : le signal est dans l'historique. On réécrit donc le
dernier message en une **requête autonome** (auto-suffisante) à partir de
l'historique, via un appel LLM léger, avant de l'embedder.

Le résultat est mis en cache sur ``ChatDeps.retrieval_query`` : un seul appel de
condensation par tour, déclenché à la demande par le premier agent qui récupère
des souvenirs (le superviseur en pratique).
"""
from __future__ import annotations

from pydantic_ai import Agent

from app.agents.deps import ChatDeps
from app.agents.model import get_agent_model
from app.agents.util.history_utils import _history_context

_CONDENSE_PROMPT = """
Tu reçois l'historique d'une conversation et le dernier message d'un utilisateur.
Réécris ce dernier message en UNE requête de recherche autonome, compréhensible
sans l'historique, qui capture l'intention réelle de l'utilisateur.

Règles :
- Résous les références implicites (« oui », « celui-là », « et pour X ? ») en
  utilisant l'historique pour retrouver le sujet concerné.
- Reste concis : une seule phrase ou un groupe nominal, sans préambule.
- N'ajoute aucune information qui n'est pas présente dans la conversation.
- Réponds UNIQUEMENT avec la requête réécrite, sans guillemets ni explication.
"""

_condense_agent = Agent(get_agent_model(), output_type=str, system_prompt=_CONDENSE_PROMPT)


async def build_retrieval_query(deps: ChatDeps, usage=None) -> str:
    """
    Renvoie la requête condensée pour récupérer les souvenirs de ce tour.

    - Mise en cache sur ``deps.retrieval_query`` (un seul appel LLM par tour).
    - Court-circuit sans appel LLM si l'historique est vide (le message brut est
      déjà auto-suffisant).
    """
    if deps.retrieval_query is not None:
        return deps.retrieval_query

    history_block = _history_context(deps.historique)
    if not history_block:
        deps.retrieval_query = deps.message
        return deps.retrieval_query

    prompt = f"{history_block}Dernier message de l'utilisateur : {deps.message}"
    try:
        result = await _condense_agent.run(prompt, usage=usage)
        condensed = (result.output or "").strip()
    except Exception as e:
        print(f"[CONDENSE] Échec de la condensation, repli sur le message brut : {e}")
        condensed = ""

    deps.retrieval_query = condensed or deps.message
    print(f"[CONDENSE] retrieval_query = {deps.retrieval_query!r}")
    return deps.retrieval_query
