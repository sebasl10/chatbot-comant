"""
HybridResearchAgent — recherche mêlant filtres exacts et thème sémantique.

Ex: « Cherche les tickets du client TPC qui parlent d'annotations 3D ».
Le thème est converti en filtre `t.id IN (...)` par `semantic_ticket_filter`, puis
combiné aux filtres exacts dans une seule requête SQL exécutée par `run_sql`.
"""

import asyncio

from pydantic_ai import Agent, ModelRetry, RunContext

from app.agents.deps import ChatDeps
from app.agents.model import DETERMINISTIC_SETTINGS, get_agent_model
from app.agents.prompts.agent_hybrid_search import build_hybrid_prompt
from app.agents.tools.db import run_sql
from app.agents.tools.entity import validate_entities
from app.agents.tools.memory import relevant_memories
from app.agents.tools.semantic import semantic_ticket_filter
from app.agents.util.output_guard import guard_against_tool_call_leak
from app.services.database import get_db_schema

hybrid_research_agent = Agent(
    get_agent_model(),
    deps_type=ChatDeps,
    # Chaîne plus longue que l'agent SQL (3 outils enchaînés) : une marge de reprise
    # supplémentaire pour les corrections SQL et les relances du garde-fou ci-dessous.
    retries=3,
    model_settings=DETERMINISTIC_SETTINGS,
)
hybrid_research_agent.tool(validate_entities)
hybrid_research_agent.tool(semantic_ticket_filter)
hybrid_research_agent.tool(run_sql)
guard_against_tool_call_leak(hybrid_research_agent)

_UNFINISHED_SEARCH = (
    "Tu as calculé le filtre sémantique mais tu n'as pas exécuté la recherche : aucun "
    "ticket n'a été cherché et l'utilisateur ne verra aucun résultat. Construis maintenant "
    "la requête SQL complète (jointures et conditions des filtres exacts, plus "
    "`AND t.id IN ({{SEMANTIC_IDS}})` recopié tel quel) et appelle `run_sql`. "
    "Ne réponds pas en texte tant que `run_sql` n'a pas réussi."
)


@hybrid_research_agent.output_validator
def _require_executed_search(ctx: RunContext[ChatDeps], output: str) -> str:
    """
    Empêche l'agent de conclure après `semantic_ticket_filter` sans avoir appelé `run_sql`.

    Le filtre sémantique seul ne cherche rien : sans `run_sql`, `deps.last_sql` reste vide,
    aucune recherche n'est persistée et le front n'affiche rien. Tant que
    `semantic_ticket_filter` n'a pas tourné (`semantic_terms` vide), l'agent a le droit de
    répondre directement : c'est le cas d'une demande de clarification sur les entités.
    """
    if ctx.deps.semantic_terms and not ctx.deps.last_sql:
        print("[GUARD] Recherche hybride sans run_sql, relance de l'agent")
        raise ModelRetry(_UNFINISHED_SEARCH)
    return output


@hybrid_research_agent.system_prompt
async def _system(ctx: RunContext[ChatDeps]) -> str:
    schema = await asyncio.to_thread(get_db_schema)
    base = build_hybrid_prompt(schema, ctx.deps.user_id)

    # L'agent hybride fait les deux métiers : il doit respecter les souvenirs
    # enregistrés pour l'agent SQL comme pour l'agent sémantique.
    memories = [
        m
        for m in (
            await relevant_memories(ctx, "sql_research"),
            await relevant_memories(ctx, "semantic_research"),
        )
        if m
    ]
    memory_block = ""
    if memories:
        memory_block = "\n\n## RÈGLES MÉMORISÉES (à respecter)\n" + "\n".join(memories)

    return base + memory_block
