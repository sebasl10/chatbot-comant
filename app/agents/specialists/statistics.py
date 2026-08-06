"""
StatisticsAgent — indicateurs agrégés (temps, répartitions, estimations) + affinage.
"""

import asyncio

from pydantic_ai import Agent, RunContext
from pydantic_ai.capabilities import Capability

from app.agents.deps import ChatDeps
from app.agents.model import DETERMINISTIC_SETTINGS, get_agent_model
from app.agents.prompts.agent_statistics import (
    ABSENCES_CAPABILITY_DESCRIPTION,
    ABSENCES_CAPABILITY_INSTRUCTIONS,
    build_statistics_affinage_prompt,
    build_statistics_prompt,
)
from app.agents.tools.db import run_external_sql, run_stats_sql
from app.agents.tools.entity import validate_entities
from app.agents.tools.memory import relevant_memories
from app.agents.tools.statistic import set_statistic_presentation
from app.agents.util.output_guard import guard_agent_output
from app.services.database import get_db_schema


absences_capability = Capability(
    id="absences",
    description=ABSENCES_CAPABILITY_DESCRIPTION,
    instructions=ABSENCES_CAPABILITY_INSTRUCTIONS,
    defer_loading=True,
)
absences_capability.tool(run_external_sql)

statistics_agent = Agent(
    get_agent_model(),
    deps_type=ChatDeps,
    retries=2,
    capabilities=[absences_capability],
    model_settings=DETERMINISTIC_SETTINGS,
)
statistics_agent.tool(validate_entities)
statistics_agent.tool(run_stats_sql)
statistics_agent.tool(set_statistic_presentation)
guard_agent_output(statistics_agent)


@statistics_agent.system_prompt
async def _system(ctx: RunContext[ChatDeps]) -> str:
    schema = await asyncio.to_thread(get_db_schema)
    if ctx.deps.mode == "affinage" and ctx.deps.previous_statistic:
        base = build_statistics_affinage_prompt(
            schema, ctx.deps.user_id, ctx.deps.previous_statistic, ctx.deps.historique
        )
    else:
        base = build_statistics_prompt(schema, ctx.deps.user_id)

    memories = await relevant_memories(ctx, "statistics")
    memory_block = f"\n\n## RÈGLES MÉMORISÉES (à respecter)\n{memories}" if memories else ""

    return base + memory_block
