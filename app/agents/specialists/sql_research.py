"""SQLResearchAgent (LangGraph) — recherche par filtres exacts + affinage.

Réutilise les prompts métier (`build_recherche_prompt`/`build_affinage_prompt`) et
y ajoute un addendum d'utilisation des outils qui active la boucle d'auto-correction.

Le system prompt dynamique (schéma + souvenirs correction_sql) est calculé par
``build_system(deps)`` et passé en ``SystemMessage`` par le wrapper de délégation.
"""
import asyncio

from langchain.agents import create_agent

from app.agents.deps import ChatDeps
from app.agents.model import get_agent_model
from app.agents.tools.db import run_sql
from app.agents.tools.entity import validate_entities
from app.prompts.recherche import build_recherche_prompt
from app.prompts.affinage import build_affinage_prompt
from app.services.database import get_db_schema
from app.services import vectorstore as vs

_TOOL_ADDENDUM = """

## OUTILS ET MÉTHODE (IMPORTANT — prioritaire sur le format de sortie ci-dessus)
Tu ne réponds JAMAIS en affichant du SQL brut. Tu utilises les outils :

1. Si le message mentionne des entités nommées (projet, utilisateur, client,
   composant, produit, tag, branche), appelle d'abord `validate_entities` pour
   les valider. Si une entité est `unknown` ou `suggestion`, demande une
   clarification à l'utilisateur au lieu de deviner.
2. Construis la requête SQL (un SELECT), puis appelle OBLIGATOIREMENT `run_sql`
   pour l'exécuter et la vérifier.
3. Si `run_sql` renvoie `{"ok": false, "error": ...}`, CORRIGE ta requête à
   partir du message d'erreur et rappelle `run_sql` (2 corrections maximum).
4. Quand `run_sql` réussit, réponds à l'utilisateur en une phrase en français,
   en indiquant le nombre de tickets trouvés (champ `count`). N'affiche pas le SQL.

Respecte impérativement les RÈGLES MÉMORISÉES ci-dessous si présentes.
"""

sql_research_agent = create_agent(get_agent_model(), [validate_entities, run_sql])


async def build_system(deps: ChatDeps) -> str:
    schema = await asyncio.to_thread(get_db_schema)
    if deps.mode == "affinage":
        base = build_affinage_prompt(schema, deps.previous_sql or "", deps.user_id, deps.historique)
    else:
        base = build_recherche_prompt(schema, deps.user_id)

    memories = await asyncio.to_thread(vs.get_memories_text, "correction_sql", deps.user_id, None)
    memory_block = f"\n\n## RÈGLES MÉMORISÉES (à respecter)\n{memories}" if memories else ""
    return base + _TOOL_ADDENDUM + memory_block
