"""MemoryAgent (LangGraph) — enregistrement des corrections/souvenirs.

Réutilise ``CORRECTION_PROMPT`` mais APPELLE le tool ``save_memory`` au lieu de
renvoyer du JSON. Types : correction_sql, expand_vocabulary, exclude_ticket,
other_correction.
"""
from langchain.agents import create_agent

from app.agents.deps import ChatDeps
from app.agents.model import get_agent_model
from app.agents.tools.memory import save_memory
from app.prompts.correction import CORRECTION_PROMPT

_ADDENDUM = """

## MÉTHODE (IMPORTANT — prioritaire sur tout format JSON décrit ci-dessus)
Au lieu de renvoyer du JSON, tu APPELLES l'outil `save_memory(type, content)` :
- `type` : correction_sql | expand_vocabulary | exclude_ticket | other_correction
- `content` : le souvenir reformulé de façon claire et réutilisable.
Puis confirme à l'utilisateur, en une phrase, ce que tu as enregistré.
"""

memory_agent = create_agent(get_agent_model(), [save_memory])


async def build_system(deps: ChatDeps) -> str:
    return CORRECTION_PROMPT + _ADDENDUM
