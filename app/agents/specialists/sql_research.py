"""
SQLResearchAgent — recherche par filtres exacts + affinage.
"""

import asyncio

from pydantic_ai import Agent, RunContext

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
from app.agents.util.output_guard import guard_against_tool_call_leak
from app.services.database import get_db_schema

sql_research_agent = Agent(
    get_agent_model(),
    deps_type=ChatDeps,
    retries=2,
    model_settings=DETERMINISTIC_SETTINGS,
)
sql_research_agent.tool(validate_entities)
sql_research_agent.tool(run_sql)
guard_against_tool_call_leak(sql_research_agent)


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
