"""SQLResearchAgent — recherche par filtres exacts + affinage.

Réutilise les prompts métier existants (``build_recherche_prompt`` /
``build_affinage_prompt`` : schéma live, valeurs de référence, règles métier,
few-shot) comme *system prompt dynamique*, et y ajoute un addendum d'utilisation
des outils qui active la boucle d'auto-correction :

    écrire SQL → run_sql → si erreur, corriger et re-run (borné) → réponse.

Les souvenirs ``correction_sql`` de l'utilisateur sont injectés dans le prompt
pour être respectés dès la génération (plus besoin d'une 2e passe de vérification).
"""
import asyncio

from pydantic_ai import Agent, RunContext

from app.agents.deps import ChatDeps
from app.agents.model import get_agent_model
from app.agents.tools.db import run_sql
from app.agents.tools.entity import validate_entities
from app.agents.tools.memory import get_memory
from app.prompts.recherche import build_recherche_prompt
from app.prompts.affinage import build_affinage_prompt
from app.services.database import get_db_schema
from app.prompts.agents.agent_sql_search import SQL_AGENT_TOOLS_PROMPT


sql_research_agent = Agent(get_agent_model(), deps_type=ChatDeps, retries=2)
sql_research_agent.tool(validate_entities)
sql_research_agent.tool(run_sql)


@sql_research_agent.system_prompt
async def _system(ctx: RunContext[ChatDeps]) -> str:
    schema = await asyncio.to_thread(get_db_schema)
    if ctx.deps.mode == "affinage":
        base = build_affinage_prompt(
            schema, ctx.deps.previous_sql or "", ctx.deps.user_id, ctx.deps.historique
        )
    else:
        base = build_recherche_prompt(schema, ctx.deps.user_id)

    # Souvenirs de correction SQL de l'utilisateur, pertinents pour ce message.
    memories = await get_memory(ctx, "correction_sql")
    memory_block = f"\n\n## RÈGLES MÉMORISÉES (à respecter)\n{memories}" if memories else ""

    return base + SQL_AGENT_TOOLS_PROMPT + memory_block
