"""
SQLResearchAgent — recherche par filtres exacts + affinage.
"""

import asyncio

from pydantic_ai import Agent, ModelRetry, RunContext

from app.agents.deps import ChatDeps
from app.agents.model import DETERMINISTIC_SETTINGS, get_agent_model
from app.agents.prompts.agent_sql_search import (
    SQL_AGENT_TOOLS_PROMPT,
    build_affinage_prompt,
    build_recherche_prompt,
)
from app.agents.tools.db import run_sql
from app.agents.tools.entity import validate_entities
from app.agents.tools.memory import relevant_memories
from app.agents.util.output_guard import guard_agent_output
from app.services.database import get_db_schema

sql_research_agent = Agent(
    get_agent_model(),
    deps_type=ChatDeps,
    retries=2,
    model_settings=DETERMINISTIC_SETTINGS,
)
sql_research_agent.tool(validate_entities)
sql_research_agent.tool(run_sql)
guard_agent_output(sql_research_agent)


@sql_research_agent.output_validator
def _require_executed_sql(ctx: RunContext[ChatDeps], output: str) -> str:
    """
    Empêche l'agent de conclure sans avoir exécuté de requête : une réponse sans SQL
    est perdue, la couche de délégation ne persistant la recherche que si
    ``deps.last_sql`` est renseigné.

    Exception : si `validate_entities` a renvoyé une entité en `suggestion`/`unknown`,
    l'agent DOIT rendre la main pour demander une clarification. Exiger du SQL dans ce
    cas le pousserait à filtrer sur une valeur non validée.
    """
    if not ctx.deps.last_sql and not ctx.deps.awaiting_entity_clarification:
        print("[GUARD] Recherche SQL sans run_sql, relance de l'agent")
        raise ModelRetry(
            "Tu as rédigé ta réponse sans qu'aucune requête SQL n'ait été exécutée : "
            "`run_sql` n'a jamais abouti, donc aucun ticket n'a été cherché et l'utilisateur "
            "ne verra aucun résultat. Construis la requête SELECT correspondant à la demande "
            "et appelle `run_sql`. Ne réponds pas en texte tant que `run_sql` n'a pas réussi."
        )
    return output


@sql_research_agent.system_prompt
async def _system(ctx: RunContext[ChatDeps]) -> str:
    schema = await asyncio.to_thread(get_db_schema)
    if ctx.deps.mode == "affinage":
        base = build_affinage_prompt(
            schema, ctx.deps.previous_sql or "", ctx.deps.user_id, ctx.deps.historique
        )
    else:
        base = build_recherche_prompt(schema, ctx.deps.user_id)

    memories = await relevant_memories(ctx, "sql_research")
    memory_block = f"\n\n## RÈGLES MÉMORISÉES (à respecter)\n{memories}" if memories else ""

    return base + SQL_AGENT_TOOLS_PROMPT + memory_block
