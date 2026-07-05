"""ConversationalAgent (LangGraph) — salutations, aide, hors-périmètre, discussion.

Sans outil. Réutilise le contenu des prompts aide/salutation/hors_perimetre.
"""
from langchain.agents import create_agent

from app.agents.deps import ChatDeps
from app.agents.model import get_agent_model
from app.prompts.aide import AIDE_SYSTEM_PROMPT
from app.prompts.salutation import SALUTATION_SYSTEM_PROMPT
from app.prompts.hors_perimetre import HORS_PERIMETRE_SYSTEM_PROMPT

_SYSTEM = f"""Tu es l'assistant conversationnel de Comant, un outil de gestion de
tickets. Tu gères les échanges qui ne sont PAS une recherche de tickets :
salutations, remerciements, questions sur tes capacités, et messages hors de ton
périmètre. Sois naturel, chaleureux et concis, comme un bon assistant.

Tu peux discuter librement, mais tu recentres poliment vers ta mission (aider à
rechercher, affiner et gérer des recherches de tickets) quand c'est pertinent.

--- Connaissances de référence ---

# Salutations
{SALUTATION_SYSTEM_PROMPT}

# Aide / capacités
{AIDE_SYSTEM_PROMPT}

# Hors périmètre
{HORS_PERIMETRE_SYSTEM_PROMPT}
"""

conversational_agent = create_agent(get_agent_model(), [])


async def build_system(deps: ChatDeps) -> str:
    return _SYSTEM
