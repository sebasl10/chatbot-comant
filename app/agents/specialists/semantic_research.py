"""
SemanticResearchAgent — recherche par thème/sujet (sémantique).

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
from app.agents.prompts.agent_semantic_research import AGENT_SEMANTIC_RESEARCH_PROMPT

semantic_research_agent = Agent(get_agent_model(), deps_type=ChatDeps, retries=2)
semantic_research_agent.tool(semantic_ticket_search)
semantic_research_agent.tool(get_memory)
semantic_research_agent.tool(run_sql)

@semantic_research_agent.system_prompt
async def _system_prompt(ctx: RunContext[ChatDeps]) -> str:
    synonyms = await get_memory(ctx, "expand_vocabulary")
    block = f"\n\n## SYNONYMES (vocabulaire métier)\n{synonyms}" if synonyms else ""
    return AGENT_SEMANTIC_RESEARCH_PROMPT + block
