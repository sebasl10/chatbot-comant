"""
MemoryAgent — enregistrement des corrections/souvenirs.
"""

from pydantic_ai import Agent, RunContext

from app.agents.deps import ChatDeps
from app.agents.model import get_agent_model
from app.agents.prompts.agent_memory import AGENT_MEMORY_PROMPT
from app.agents.tools.memory import delete_memory, relevant_memories, save_memory, update_memory
from app.agents.util.output_guard import guard_against_tool_call_leak

memory_agent = Agent(get_agent_model(), deps_type=ChatDeps, retries=2)
memory_agent.tool(save_memory)
memory_agent.tool(delete_memory)
memory_agent.tool(update_memory)
guard_against_tool_call_leak(memory_agent)


@memory_agent.system_prompt
async def _system(ctx: RunContext[ChatDeps]) -> str:
    memories = await relevant_memories(ctx, "memory")
    memory_block = f"\n\n## RÈGLES MÉMORISÉES (à respecter)\n{memories}" if memories else ""
    return AGENT_MEMORY_PROMPT + memory_block
