"""SemanticResearchAgent (LangGraph) — recherche par thème/sujet.

Séquence typique : semantic_ticket_search → WHERE t.id IN (...) → exclusions
(get_memory 'exclude_ticket') → run_sql. Les synonymes ``expand_vocabulary`` sont
injectés dans le system prompt.
"""
import asyncio

from langchain.agents import create_agent

from app.agents.deps import ChatDeps
from app.agents.model import get_agent_model
from app.agents.tools.db import run_sql
from app.agents.tools.memory import get_memory
from app.agents.tools.semantic import semantic_ticket_search
from app.services import vectorstore as vs

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

semantic_research_agent = create_agent(
    get_agent_model(), [semantic_ticket_search, get_memory, run_sql]
)


async def build_system(deps: ChatDeps) -> str:
    synonyms = await asyncio.to_thread(vs.get_memories_text, "expand_vocabulary", deps.user_id, None)
    block = f"\n\n## SYNONYMES (vocabulaire métier)\n{synonyms}" if synonyms else ""
    return _SYSTEM + block
