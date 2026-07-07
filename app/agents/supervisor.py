"""
Superviseur — reçoit le message et délègue à un agent spécialiste.

Le superviseur choisit UN outil de délégation (ou répond via l'agent conversationnel), relaie la réponse du
spécialiste, et reste léger.
"""
import asyncio
from pydantic_ai import Agent, RunContext
from app.agents.deps import ChatDeps
from app.agents.model import get_agent_model
from app.agents.specialists.conversational import conversational_agent
from app.agents.specialists.sql_research import sql_research_agent
from app.agents.specialists.semantic_research import semantic_research_agent
from app.agents.specialists.memory import memory_agent
from app.agents.tools.research import persist_new_research, persist_affinage
from app.services.database import get_sql, rename_research as db_rename_research, delete_research as db_delete_research
from app.prompts.agents.agent_supervisor import AGENT_SUPERVISOR_PROMPT

supervisor_agent = Agent(
    get_agent_model(), 
    deps_type=ChatDeps, 
    system_prompt=AGENT_SUPERVISOR_PROMPT
)

@supervisor_agent.tool
async def delegate_conversation(ctx: RunContext[ChatDeps], message: str) -> str:
    """
    Délègue à l'agent conversationnel (salutation, aide, hors-périmètre, discussion) et retourne sa réponse exacte, sans aucune modification.
    Reçoit comme paramètre le message envoyé par l'utilisateur
    Retourne un string que doit être renvoyé tel quel à l'utilisateur
    """
    print("[DELEGATE] Conversational agent")
    ctx.deps.events.intention("conversation")
    result = await conversational_agent.run(message, deps=ctx.deps, usage=ctx.usage)
    print(f"-> {result.output}")
    return result.output

@supervisor_agent.tool
async def delegate_new_search(ctx: RunContext[ChatDeps], request: str) -> str:
    """Délègue une NOUVELLE recherche par filtres exacts à l'agent SQL, puis
    persiste la recherche créée."""
    print("[DELEGATE] SQL research agent")
    ctx.deps.events.intention("recherche")
    ctx.deps.mode = "recherche"
    result = await sql_research_agent.run(request, deps=ctx.deps, usage=ctx.usage)
    if ctx.deps.last_sql:
        await persist_new_research(ctx.deps)
    return result.output

@supervisor_agent.tool
async def delegate_refine_search(ctx: RunContext[ChatDeps], request: str) -> str:
    """Délègue l'AFFINAGE de la dernière recherche à l'agent SQL, puis met à jour
    la recherche existante."""
    print("[DELEGATE] SQL research agent (affinage)")
    ctx.deps.events.intention("affinage")
    ctx.deps.mode = "affinage"
    ctx.deps.previous_sql = _previous_sql(ctx.deps)
    prompt = f"Requête SQL précédente : {ctx.deps.previous_sql}\nDemande d'affinage : {request}"
    result = await sql_research_agent.run(prompt, deps=ctx.deps, usage=ctx.usage)
    if ctx.deps.last_sql:
        await persist_affinage(ctx.deps)
    return result.output

@supervisor_agent.tool
async def delegate_semantic_search(ctx: RunContext[ChatDeps], subject: str) -> str:
    """Délègue une recherche par thème/sujet à l'agent sémantique, puis persiste."""
    print("[DELEGATE] Semantic research agent")   
    ctx.deps.events.intention("recherche_semantique")
    ctx.deps.mode = "recherche"
    result = await semantic_research_agent.run(subject, deps=ctx.deps, usage=ctx.usage)
    if ctx.deps.last_sql:
        await persist_new_research(ctx.deps)
    return result.output

@supervisor_agent.tool
async def delegate_correction(ctx: RunContext[ChatDeps], message: str) -> str:
    """Délègue l'enregistrement d'une correction/souvenir à l'agent mémoire."""
    print("[DELEGATE] Memory agent")   
    ctx.deps.events.intention("correction")
    result = await memory_agent.run(message, deps=ctx.deps, usage=ctx.usage)
    return result.output

@supervisor_agent.tool
async def rename_research(ctx: RunContext[ChatDeps], name: str, research_id: int = 0) -> str:
    """Renomme / sauvegarde la recherche courante (ou celle d'id `research_id`)."""
    print("[TOOL CALL] Rename research")  
    rid = research_id or ctx.deps.research_id
    if not rid:
        return "Aucune recherche courante à sauvegarder."
    await asyncio.to_thread(db_rename_research, rid, name, ctx.deps.user_id)
    ctx.deps.events.action("rename_research", research_id=rid, new_name=name)
    return f"Recherche sauvegardée sous le nom « {name} »."

@supervisor_agent.tool
async def delete_research(ctx: RunContext[ChatDeps], research_id: int = 0) -> str:
    """Supprime la recherche courante (ou celle d'id `research_id`)."""
    print("[TOOL CALL] Delete research")  
    rid = research_id or ctx.deps.research_id
    if not rid:
        return "Aucune recherche courante à supprimer."
    await asyncio.to_thread(db_delete_research, rid, ctx.deps.user_id)
    ctx.deps.events.action("delete_research", research_id=rid)
    return "Recherche supprimée."

def _previous_sql(deps: ChatDeps) -> str:
    """Retrouve la requête SQL à affiner : d'abord via research_id, sinon l'historique."""
    if deps.research_id:
        try:
            return get_sql(deps.research_id)
        except Exception:
            pass
    for msg in reversed(deps.historique):
        if msg.get("sql") or msg.get("generated_sql"):
            return msg.get("sql") or msg.get("generated_sql")
    return ""
