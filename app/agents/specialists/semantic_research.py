"""
SemanticResearchAgent — recherche par thème/sujet (sémantique).

Deux capabilities chargées à la demande (load_capability) selon l'intention détectée
par le prompt de base, pour éviter de mélanger vocabulaire et recherche de tickets
dans le même contexte :

    - "vocabulary"    : get_vocabulary_for_term / remove_term_from_vocabulary.
    - "ticket_search" : semantic_ticket_search(sujet) → sql_query déjà construite → run_sql.
"""
from pydantic_ai import Agent, RunContext
from pydantic_ai.capabilities import Capability
from app.agents.deps import ChatDeps
from app.agents.model import get_agent_model
from app.agents.tools.memory import relevant_memories
from app.agents.tools.semantic import semantic_ticket_search, get_vocabulary_for_term, remove_term_from_vocabulary
from app.agents.prompts.agent_semantic_research import (
    BASE_SEMANTIC_RESEARCH_PROMPT,
    VOCABULARY_CAPABILITY_DESCRIPTION,
    VOCABULARY_CAPABILITY_INSTRUCTIONS,
    TICKET_SEARCH_CAPABILITY_DESCRIPTION,
    TICKET_SEARCH_CAPABILITY_INSTRUCTIONS,
)
from app.agents.util.output_guard import guard_against_tool_call_leak

vocabulary_capability = Capability(
    id="vocabulary",
    description=VOCABULARY_CAPABILITY_DESCRIPTION,
    instructions=VOCABULARY_CAPABILITY_INSTRUCTIONS,
    defer_loading=True,
)
vocabulary_capability.tool(get_vocabulary_for_term)
vocabulary_capability.tool(remove_term_from_vocabulary)

ticket_search_capability = Capability(
    id="ticket_search",
    description=TICKET_SEARCH_CAPABILITY_DESCRIPTION,
    instructions=TICKET_SEARCH_CAPABILITY_INSTRUCTIONS,
    defer_loading=True,
)
ticket_search_capability.tool(semantic_ticket_search)

semantic_research_agent = Agent(
    get_agent_model(),
    deps_type=ChatDeps,
    retries=2,
    capabilities=[vocabulary_capability, ticket_search_capability],
)
guard_against_tool_call_leak(semantic_research_agent)


@semantic_research_agent.system_prompt
async def _system(ctx: RunContext[ChatDeps]) -> str:
    # Souvenirs sémantiques de l'utilisateur (exclusions, autres corrections),
    # pertinents pour ce message. Le vocabulaire passe par les tools, pas ici.
    memories = await relevant_memories(ctx, "semantic_research")
    memory_block = f"\n\n## RÈGLES MÉMORISÉES (à respecter)\n{memories}" if memories else ""
    return BASE_SEMANTIC_RESEARCH_PROMPT + memory_block
