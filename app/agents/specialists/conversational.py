"""
ConversationalAgent — salutations, aide, hors-périmètre, conversation libre.
"""
import asyncio
from pydantic_ai import Agent, RunContext

from app.agents.deps import ChatDeps
from app.agents.model import get_agent_model
from app.agents.prompts.agent_conversational import AGENT_CONVERSATIONAL_PROMPT
from app.agents.util.history_utils import _history_context

conversational_agent = Agent(
    get_agent_model(), 
    deps_type=ChatDeps,
)


@conversational_agent.system_prompt
async def _system(ctx: RunContext[ChatDeps]) -> str:
    history_block = await asyncio.to_thread(_history_context, ctx.deps.historique)
    return AGENT_CONVERSATIONAL_PROMPT + history_block
