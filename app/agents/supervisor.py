"""Superviseur — reçoit le message et délègue à un agent spécialiste.

Topologie « superviseur + spécialistes bornés » : le superviseur choisit UN outil
de délégation (ou répond via l'agent conversationnel), relaie la réponse du
spécialiste, et reste léger.

La persistance des recherches (create/update `research`) est faite ici, de façon
DÉTERMINISTE, après qu'un agent SQL/sémantique a produit une requête valide
(mémorisée dans ``deps.last_sql`` par le tool ``run_sql``). Ces helpers émettent
l'événement ``research`` que le front consomme.
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

_SYSTEM = """Tu es le superviseur d'un chatbot de recherche de tickets (Comant).
Tu reçois le message de l'utilisateur et tu choisis QUOI faire, en appelant UN
seul outil de délégation, puis tu relaies fidèlement sa réponse à l'utilisateur.

Outils de délégation :
- `delegate_conversation` : salutations, remerciements, aide/capacités, questions
  hors périmètre, ou toute conversation qui n'est pas une recherche.
- `delegate_new_search` : NOUVELLE recherche de tickets par filtres exacts
  (projet, utilisateur, statut, dates, priorité...). Ex: "tickets du projet X créés par Y".
- `delegate_refine_search` : AFFINER la dernière recherche (ajouter/retirer/modifier
  un filtre). Ex: "garde seulement ceux du projet Comant2026", "enlève les fermés".
- `delegate_semantic_search` : recherche par THÈME/SUJET, pas par filtres exacts.
  Ex: "les tickets qui parlent de cinématique".
- `delegate_correction` : l'utilisateur corrige ton comportement ou te demande de
  RETENIR une règle/synonyme/exclusion. Ex: "utilise la table projet_ticket",
  "cinématique inclut aussi vitesse de rotation".

Outils directs sur la recherche courante :
- `rename_research` : SAUVEGARDER / renommer la recherche courante.
  Ex: "sauvegarde cette recherche sous le nom Bugs Comant", "renomme-la X".
- `delete_research` : SUPPRIMER la recherche courante. Ex: "supprime cette recherche".

Règles :
- Choisis `delegate_refine_search` seulement s'il existe une recherche en cours à
  affiner ; sinon `delegate_new_search`.
- Après l'outil, réponds en français en relayant la réponse du spécialiste.
  N'affiche jamais de SQL.
"""


supervisor_agent = Agent(get_agent_model(), deps_type=ChatDeps, system_prompt=_SYSTEM)


@supervisor_agent.tool
async def delegate_conversation(ctx: RunContext[ChatDeps], message: str) -> str:
    """Délègue à l'agent conversationnel (salutation, aide, hors-périmètre, discussion)."""
    ctx.deps.events.intention("conversation")
    result = await conversational_agent.run(message, deps=ctx.deps, usage=ctx.usage)
    return result.output


@supervisor_agent.tool
async def delegate_new_search(ctx: RunContext[ChatDeps], request: str) -> str:
    """Délègue une NOUVELLE recherche par filtres exacts à l'agent SQL, puis
    persiste la recherche créée."""
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
    ctx.deps.events.intention("recherche_semantique")
    ctx.deps.mode = "recherche"
    result = await semantic_research_agent.run(subject, deps=ctx.deps, usage=ctx.usage)
    if ctx.deps.last_sql:
        await persist_new_research(ctx.deps)
    return result.output


@supervisor_agent.tool
async def delegate_correction(ctx: RunContext[ChatDeps], message: str) -> str:
    """Délègue l'enregistrement d'une correction/souvenir à l'agent mémoire."""
    ctx.deps.events.intention("correction")
    result = await memory_agent.run(message, deps=ctx.deps, usage=ctx.usage)
    return result.output


@supervisor_agent.tool
async def rename_research(ctx: RunContext[ChatDeps], name: str, research_id: int = 0) -> str:
    """Renomme / sauvegarde la recherche courante (ou celle d'id `research_id`)."""
    rid = research_id or ctx.deps.research_id
    if not rid:
        return "Aucune recherche courante à sauvegarder."
    await asyncio.to_thread(db_rename_research, rid, name, ctx.deps.user_id)
    ctx.deps.events.action("rename_research", research_id=rid, new_name=name)
    return f"Recherche sauvegardée sous le nom « {name} »."


@supervisor_agent.tool
async def delete_research(ctx: RunContext[ChatDeps], research_id: int = 0) -> str:
    """Supprime la recherche courante (ou celle d'id `research_id`)."""
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
