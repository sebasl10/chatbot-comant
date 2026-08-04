"""
Superviseur — reçoit le message et délègue à un agent spécialiste.
"""

import asyncio

from pydantic_ai import Agent, RunContext

from app.agents.deps import ChatDeps
from app.agents.model import get_agent_model
from app.agents.prompts.agent_supervisor import AGENT_SUPERVISOR_PROMPT
from app.agents.specialists.conversational import conversational_agent
from app.agents.specialists.memory import memory_agent
from app.agents.specialists.semantic_research import semantic_research_agent
from app.agents.specialists.sql_research import sql_research_agent
from app.agents.specialists.statistics import statistics_agent
from app.agents.tools.memory import relevant_memories
from app.agents.tools.research import persist_affinage, persist_new_research
from app.agents.tools.statistic import persist_statistic
from app.agents.util.history_utils import _history_context
from app.agents.util.output_guard import guard_against_tool_call_leak
from app.services.database import delete_research as db_delete_research
from app.services.database import delete_statistic as db_delete_statistic
from app.services.database import get_sql, is_admin
from app.services.database import rename_research as db_rename_research
from app.services.database import rename_statistic as db_rename_statistic


async def delegate_conversation(ctx: RunContext[ChatDeps], user_message: str) -> str:
    """
    Délègue à l'agent conversationnel (salutation, aide, hors-périmètre, discussion).
    Args:
        message: Message exact envoyé par l'utilisateur, sans modification, sans reformulation, sans ajout de texte
    """
    print("[DELEGATE] Conversational agent ")
    print(f"Message: {user_message}")
    ctx.deps.events.intention("conversation")
    result = await conversational_agent.run(user_message, deps=ctx.deps, usage=ctx.usage)
    print(f"-> {result.output}")
    return result.output


async def delegate_new_research(ctx: RunContext[ChatDeps], request: str) -> str:
    """
    Délègue une NOUVELLE recherche par filtres exacts à l'agent SQL, puis persiste la recherche créée.
    Args:
        request: Message contenant la requête de l'utilisateur (message envoyé par l'utilisateur ou construit à partir de l'historique)
    """
    print("[DELEGATE] SQL research agent")
    print(f"Message: {request}")
    ctx.deps.events.early_intention("recherche")
    ctx.deps.mode = "recherche"
    result = await sql_research_agent.run(request, deps=ctx.deps, usage=ctx.usage)
    if ctx.deps.last_sql:
        await persist_new_research(ctx.deps, False, intention="recherche")
    return result.output


async def delegate_refine_search(ctx: RunContext[ChatDeps], request: str) -> str:
    """
    Délègue l'AFFINAGE de la dernière recherche à l'agent SQL, puis met à jour
    la recherche existante.
    Args:
        request: Message exact envoyé par l'utilisateur, sans modification, sans reformulation, sans ajout de texte
    """
    print("[DELEGATE] SQL research agent (affinage)")
    ctx.deps.events.early_intention("affinage")
    ctx.deps.mode = "affinage"
    ctx.deps.previous_sql = _previous_sql(ctx.deps)
    print(f"LAST SQL: {ctx.deps.previous_sql}")
    prompt = f"Requête SQL précédente : {ctx.deps.previous_sql}\nDemande d'affinage : {request}"
    result = await sql_research_agent.run(prompt, deps=ctx.deps, usage=ctx.usage)
    if ctx.deps.last_sql:
        await persist_affinage(ctx.deps, intention="affinage")
    return result.output


async def delegate_semantic_search(ctx: RunContext[ChatDeps], request: str) -> str:
    """
    Délègue une recherche par thème/sujet à l'agent sémantique, puis persiste.
    Args:
        request: Message exact envoyé par l'utilisateur, sans modification, sans reformulation, sans ajout de texte
    """
    print("[DELEGATE] Semantic research agent")
    print(f"Message: {request}")
    ctx.deps.events.early_intention("recherche")
    ctx.deps.mode = "recherche"
    result = await semantic_research_agent.run(request, deps=ctx.deps, usage=ctx.usage)
    if ctx.deps.last_sql:
        await persist_new_research(ctx.deps, True, intention="recherche")
    return result.output


async def delegate_statistics(ctx: RunContext[ChatDeps], request: str) -> str:
    """
    Délègue le calcul d'une STATISTIQUE (indicateur agrégé) à l'agent statistiques.
    Args:
        request: Message exact envoyé par l'utilisateur, sans modification, sans reformulation, sans ajout de texte
    """
    print("[DELEGATE] Statistics agent")
    print(f"Message: {request}")

    # Vérifier si l'utilisateur est Admin
    is_user_admin = is_admin(ctx.deps.user_id)
    if not (is_user_admin):
        return "Vous n'êtes pas autorisé·e à générer des statistiques. Cette fonctionnalité est réservée aux administrateurs."

    ctx.deps.events.early_intention("statistic")
    ctx.deps.last_stats_sql = None
    ctx.deps.last_result = None
    ctx.deps.last_stats_columns = []
    ctx.deps.external_sql = None
    ctx.deps.external_result = None
    ctx.deps.external_columns = []
    ctx.deps.graph_type = None
    ctx.deps.description = None
    ctx.deps.labels = None
    result = await statistics_agent.run(request, deps=ctx.deps, usage=ctx.usage)

    if ctx.deps.last_stats_sql:
        await persist_statistic(ctx.deps)

    return result.output


async def delegate_correction(ctx: RunContext[ChatDeps], message: str) -> str:
    """
    Délègue l'enregistrement d'une correction/souvenir à l'agent mémoire.
    """
    print("[DELEGATE] Memory agent")
    ctx.deps.events.intention("correction")
    prompt = _history_context(ctx.deps.historique) + message
    result = await memory_agent.run(prompt, deps=ctx.deps, usage=ctx.usage)
    return result.output


supervisor_agent = Agent(
    get_agent_model(),
    deps_type=ChatDeps,
    output_type=[
        str,
        delegate_conversation,
        delegate_new_research,
        delegate_refine_search,
        delegate_semantic_search,
        delegate_statistics,
        delegate_correction,
    ],
    retries=2,
)
guard_against_tool_call_leak(supervisor_agent)


@supervisor_agent.system_prompt
async def _system(ctx: RunContext[ChatDeps]) -> str:
    memories = await relevant_memories(ctx, "supervisor")
    memory_block = (
        f"\n\n## GUIDE DE ROUTAGE (exemples et corrections à respecter)\n{memories}"
        if memories
        else ""
    )
    return AGENT_SUPERVISOR_PROMPT + memory_block


@supervisor_agent.tool
async def rename_research(ctx: RunContext[ChatDeps], name: str, research_id: int = 0) -> str:
    """
    Renomme / sauvegarde la recherche courante (ou celle d'id `research_id`) avec un nom donné par l'utilisateur.
    Args:
        name: Nouveau nom de la recherche. Il doit être explicitement fourni par l'utilisateur.
        research_id: ID de la recherche qui doit être sauvegardée ou renommée
    """
    print("[TOOL CALL] Rename research")
    rid = research_id or ctx.deps.research_id
    print(f"Research ID: {rid}")
    print(f"Name: {name}")
    if not rid:
        return "Aucune recherche courante à sauvegarder."
    await asyncio.to_thread(db_rename_research, rid, name, ctx.deps.user_id)
    ctx.deps.events.action("rename_research", research_id=rid, new_name=name)
    return f"Recherche sauvegardée sous le nom « {name} »."


@supervisor_agent.tool
async def delete_research(ctx: RunContext[ChatDeps], research_id: int = 0) -> str:
    """
    Supprime la recherche courante (ou celle d'id `research_id`).
    Args:
        research_id: ID de la recherche qui doit être supprimée
    """
    print("[TOOL CALL] Delete research")
    rid = research_id or ctx.deps.research_id
    print(f"Research ID: {rid}")
    if not rid:
        return "Aucune recherche courante à supprimer."
    await asyncio.to_thread(db_delete_research, rid, ctx.deps.user_id)
    ctx.deps.events.action("delete_research", research_id=rid)
    return "Recherche supprimée."


@supervisor_agent.tool
async def rename_statistic(ctx: RunContext[ChatDeps], name: str, statistic_id: int = 0) -> str:
    """
    Renomme / sauvegarde la statistique courante (ou celle d'id `statistic_id`) avec un nom donné par l'utilisateur.
    Args:
        name: Nouveau nom de la statistique. Il doit être explicitement fourni par l'utilisateur.
        statistic_id: ID de la statistique qui doit être sauvegardée ou renommée
    """
    print("[TOOL CALL] Rename statistic")
    sid = statistic_id or ctx.deps.statistic_id
    print(f"Statistic ID: {sid}")
    print(f"Name: {name}")
    if not sid:
        return "Aucune statistique courante à sauvegarder."
    await asyncio.to_thread(db_rename_statistic, sid, name, ctx.deps.user_id)
    ctx.deps.events.action("rename_statistic", statistic_id=sid, new_name=name)
    return f"Statistique sauvegardée sous le nom « {name} »."


@supervisor_agent.tool
async def delete_statistic(ctx: RunContext[ChatDeps], statistic_id: int = 0) -> str:
    """
    Supprime la statistique courante (ou celle d'id `statistic_id`).
    Args:
        statistic_id: ID de la statistique qui doit être supprimée
    """
    print("[TOOL CALL] Delete statistic")
    sid = statistic_id or ctx.deps.statistic_id
    print(f"Statistic ID: {sid}")
    if not sid:
        return "Aucune statistique courante à supprimer."
    await asyncio.to_thread(db_delete_statistic, sid, ctx.deps.user_id)
    ctx.deps.events.action("delete_statistic", statistic_id=sid)
    return "Statistique supprimée."


def _previous_sql(deps: ChatDeps) -> str:
    """
    Retrouve la requête SQL à affiner : d'abord via research_id, sinon l'historique.
    """
    if deps.research_id:
        try:
            return get_sql(deps.research_id)
        except Exception:
            pass
    for msg in reversed(deps.historique):
        if msg.get("sql") or msg.get("generated_sql"):
            return msg.get("sql") or msg.get("generated_sql")
    return ""
