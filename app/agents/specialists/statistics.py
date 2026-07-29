"""
StatisticsAgent — indicateurs agrégés (temps, répartitions, estimations).
"""
import asyncio

from pydantic_ai import Agent, RunContext

from app.agents.deps import ChatDeps
from app.agents.model import get_agent_model
from app.agents.tools.db import run_stats_sql
from app.agents.tools.entity import validate_entities
from app.agents.tools.memory import relevant_memories
from app.services.database import get_db_schema
from app.agents.prompts.agent_statistics import build_statistics_prompt
from app.agents.util.output_guard import guard_against_tool_call_leak


statistics_agent = Agent(
    get_agent_model(),
    deps_type=ChatDeps,
    retries=2
)
statistics_agent.tool(validate_entities)
statistics_agent.tool(run_stats_sql)
guard_against_tool_call_leak(statistics_agent)


@statistics_agent.system_prompt
async def _system(ctx: RunContext[ChatDeps]) -> str:
    schema = await asyncio.to_thread(get_db_schema)
    base = build_statistics_prompt(schema, ctx.deps.user_id)

    memories = await relevant_memories(ctx, "statistics")
    memory_block = f"\n\n## RÈGLES MÉMORISÉES (à respecter)\n{memories}" if memories else ""

    return base + memory_block
