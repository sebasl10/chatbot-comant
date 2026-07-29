"""StatisticsAgent — indicateurs agrégés (temps, répartitions, estimations).

Même principe que ``SQLResearchAgent``, mais orienté agrégats : le prompt métier
(``build_statistics_prompt`` : schéma live, valeurs de référence, règles de calcul
du temps effectif / estimé / R&D / absences, few-shot) sert de *system prompt
dynamique*, complété par un addendum d'utilisation des outils qui active la boucle
d'auto-correction :

    écrire SQL d'agrégation → run_stats_sql → si erreur, corriger et re-run (borné) → réponse.

Différence avec l'agent de recherche : la requête produite n'est PAS persistée en
tant que recherche. Pour cette première version, elle est simplement affichée dans
le chat par la couche de délégation (``delegate_statistics``), à partir de
``deps.last_stats_sql`` — jamais recopiée par le modèle.
"""
import asyncio

from pydantic_ai import Agent, RunContext

from app.agents.deps import ChatDeps
from app.agents.model import get_agent_model
from app.agents.tools.db import run_stats_sql
from app.agents.tools.entity import validate_entities
from app.agents.tools.memory import relevant_memories
from app.services.database import get_db_schema
from app.agents.prompts.agent_statistics import STATISTICS_AGENT_TOOLS_PROMPT, build_statistics_prompt
from app.agents.util.output_guard import guard_against_tool_call_leak


statistics_agent = Agent(
    get_agent_model(),
    deps_type=ChatDeps,
    retries=2
)
statistics_agent.tool(validate_entities)
statistics_agent.tool(run_stats_sql)
guard_against_tool_call_leak(statistics_agent)


@statistics_agent.system_prompt
async def _system(ctx: RunContext[ChatDeps]) -> str:
    schema = await asyncio.to_thread(get_db_schema)
    base = build_statistics_prompt(schema, ctx.deps.user_id)

    memories = await relevant_memories(ctx, "statistics")
    memory_block = f"\n\n## RÈGLES MÉMORISÉES (à respecter)\n{memories}" if memories else ""

    return base + STATISTICS_AGENT_TOOLS_PROMPT + memory_block
