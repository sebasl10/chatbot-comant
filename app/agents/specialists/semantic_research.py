"""SemanticResearchAgent — recherche par thème/sujet (sémantique).

Séquence d'outils typique :
    semantic_ticket_search(sujet) → ids
    → construire "SELECT ... WHERE t.id IN (ids)"
    → (optionnel) exclure les tickets mémorisés (get_memory 'exclude_ticket')
    → run_sql

Les synonymes ``expand_vocabulary`` (globaux) sont injectés dans le prompt pour
aider à formuler un bon sujet de recherche.
"""
from pydantic_ai import Agent, RunContext

from app.agents.deps import ChatDeps
from app.agents.model import get_agent_model
from app.agents.tools.db import run_sql
from app.agents.tools.memory import get_memory
from app.agents.tools.semantic import semantic_ticket_search

_SYSTEM = """Tu es un agent de recherche sémantique de tickets. L'utilisateur
cherche des tickets par THÈME/SUJET (ex: "les tickets qui parlent de cinématique"),
pas par filtres exacts.

MÉTHODE (utilise les outils, ne renvoie jamais de SQL brut) :
1. Extrais le sujet de recherche du message (quelques mots-clés), en t'aidant des
   SYNONYMES ci-dessous si pertinents.
2. Appelle `semantic_ticket_search(query=<sujet>)` pour obtenir les `ticket_ids`.
3. Si aucun ticket : réponds qu'aucun ticket ne correspond.
   Sinon, construis la requête :
   `SELECT t.id, t.summary, t.description FROM ticket t WHERE t.id IN (<ids>)`.
4. Appelle `get_memory(type="exclude_ticket")`. Si des codes de tickets doivent
   être exclus, ajoute ` AND t.code NOT IN ('CODE1', 'CODE2')` à la requête.
5. Appelle OBLIGATOIREMENT `run_sql` avec la requête finale.
6. Réponds en une phrase en français avec le nombre de tickets trouvés (`count`).
   N'affiche pas le SQL.
"""


semantic_research_agent = Agent(get_agent_model(), deps_type=ChatDeps, retries=2)
semantic_research_agent.tool(semantic_ticket_search)
semantic_research_agent.tool(get_memory)
semantic_research_agent.tool(run_sql)


@semantic_research_agent.system_prompt
async def _system_prompt(ctx: RunContext[ChatDeps]) -> str:
    synonyms = await get_memory(ctx, "expand_vocabulary")
    block = f"\n\n## SYNONYMES (vocabulaire métier)\n{synonyms}" if synonyms else ""
    return _SYSTEM + block
