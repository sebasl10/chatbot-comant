"""MemoryAgent — enregistrement des corrections/souvenirs.

Remplace l'ancienne intention `correction`. Analyse le message + l'historique,
détermine le type de correction, puis appelle l'outil `save_memory` (Chroma).

Réutilise ``CORRECTION_PROMPT`` comme base, avec un addendum qui bascule la
sortie « JSON » vers un appel d'outil.

Types : correction_sql, expand_vocabulary, exclude_ticket, other_correction.
"""
from pydantic_ai import Agent

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


memory_agent = Agent(get_agent_model(), deps_type=ChatDeps, retries=2)
memory_agent.tool(save_memory)


@memory_agent.system_prompt
def _system() -> str:
    return CORRECTION_PROMPT + _ADDENDUM
