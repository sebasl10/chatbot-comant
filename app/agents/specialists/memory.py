"""
MemoryAgent — enregistrement des corrections/souvenirs.

Types : correction_sql, expand_vocabulary, exclude_ticket, other_correction.
"""
from pydantic_ai import Agent
from app.agents.deps import ChatDeps
from app.agents.model import get_agent_model
from app.agents.tools.memory import save_memory, delete_memory, update_memory
from app.prompts.agents.agent_memory import AGENT_MEMORY_PROMPT

memory_agent = Agent(get_agent_model(), deps_type=ChatDeps, retries=2, system_prompt=AGENT_MEMORY_PROMPT)
memory_agent.tool(save_memory)
memory_agent.tool(delete_memory)
memory_agent.tool(update_memory)