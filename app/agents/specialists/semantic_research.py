"""
SemanticResearchAgent — recherche par thème/sujet (sémantique).

Séquence d'outils typique :
    semantic_ticket_search(sujet) → ids (utilise automatiquement les synonymes expand_vocabulary)
    → construire "SELECT ... WHERE t.id IN (ids)"
    → (optionnel) exclure les tickets mémorisés (get_memory 'exclude_ticket')
    → run_sql
    
    Pour les questions de vocabulaire :
    get_vocabulary_for_term(terme) → liste des synonymes
"""
from pydantic_ai import Agent
from app.agents.deps import ChatDeps
from app.agents.model import get_agent_model
from app.agents.tools.db import run_sql
from app.agents.tools.memory import get_memory
from app.agents.tools.semantic import semantic_ticket_search, get_vocabulary_for_term, remove_term_from_vocabulary
from app.agents.prompts.agent_semantic_research import AGENT_SEMANTIC_RESEARCH_PROMPT
from app.agents.util.output_guard import guard_against_tool_call_leak

semantic_research_agent = Agent(get_agent_model(), deps_type=ChatDeps, retries=2, system_prompt=AGENT_SEMANTIC_RESEARCH_PROMPT)
semantic_research_agent.tool(semantic_ticket_search)
semantic_research_agent.tool(get_vocabulary_for_term)
semantic_research_agent.tool(remove_term_from_vocabulary)
semantic_research_agent.tool(get_memory)
semantic_research_agent.tool(run_sql)
guard_against_tool_call_leak(semantic_research_agent)