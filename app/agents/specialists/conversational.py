"""
ConversationalAgent — salutations, aide, hors-périmètre, conversation libre.
"""
from pydantic_ai import Agent

from app.agents.deps import ChatDeps
from app.agents.model import get_agent_model
from app.prompts.agents.agent_conversational import AGENT_CONVERSATIONAL_PROMPT

conversational_agent = Agent(get_agent_model(), deps_type=ChatDeps, system_prompt=AGENT_CONVERSATIONAL_PROMPT)
