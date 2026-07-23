"""
ConversationalAgent — salutations, aide, hors-périmètre, conversation libre.
"""
import asyncio
from pydantic_ai import Agent, RunContext

from app.agents.deps import ChatDeps
from app.agents.model import get_agent_model
from app.agents.prompts.agent_conversational import AGENT_CONVERSATIONAL_PROMPT
from app.agents.tools.memory import relevant_memories
from app.agents.util.history_utils import _history_context
from app.agents.util.output_guard import guard_against_tool_call_leak

conversational_agent = Agent(
    get_agent_model(),
    deps_type=ChatDeps,
    retries=2,
)
guard_against_tool_call_leak(conversational_agent)


@conversational_agent.system_prompt
async def _system(ctx: RunContext[ChatDeps]) -> str:
    history_block = await asyncio.to_thread(_history_context, ctx.deps.historique)
    memories = await relevant_memories(ctx, "conversational")
    memory_block = f"\n\n## RÈGLES MÉMORISÉES (à respecter)\n{memories}" if memories else ""
    return AGENT_CONVERSATIONAL_PROMPT + history_block + memory_block
