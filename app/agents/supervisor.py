"""Superviseur (LangGraph) — reçoit le message et délègue à un spécialiste.

Pattern « agents-as-tools » : le superviseur est un ``create_agent`` dont les tools
sont des fonctions de délégation qui invoquent les agents spécialistes
(``specialist.ainvoke(...)``), persistent la recherche et émettent les événements.

Logique de persistance/événements identique à la branche Pydantic AI.
"""
import asyncio

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langchain.agents import create_agent

from app.agents.context import deps_from_config
from app.agents.deps import ChatDeps
from app.agents.model import get_agent_model
from app.agents.specialists import conversational, sql_research, semantic_research
from app.agents.specialists import memory as memory_spec
from app.agents.tools.research import persist_new_research, persist_affinage
from app.services.database import (
    get_sql,
    rename_research as db_rename_research,
    delete_research as db_delete_research,
)

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
  RETENIR une règle/synonyme/exclusion. Ex: "utilise la table projet_ticket".

Outils directs sur la recherche courante :
- `rename_research` : SAUVEGARDER / renommer la recherche courante.
- `delete_research` : SUPPRIMER la recherche courante.

Règles :
- Choisis `delegate_refine_search` seulement s'il existe une recherche en cours à
  affiner ; sinon `delegate_new_search`.
- Après l'outil, réponds en français en relayant la réponse du spécialiste.
  N'affiche jamais de SQL.
"""


async def _run_specialist(agent, build_system, request: str, deps: ChatDeps, config: RunnableConfig) -> str:
    system = await build_system(deps)
    result = await agent.ainvoke(
        {"messages": [SystemMessage(content=system), HumanMessage(content=request)]},
        config,
    )
    return result["messages"][-1].content


@tool
async def delegate_conversation(message: str, config: RunnableConfig) -> str:
    """Délègue à l'agent conversationnel (salutation, aide, hors-périmètre, discussion)."""
    deps = deps_from_config(config)
    deps.events.intention("conversation")
    return await _run_specialist(
        conversational.conversational_agent, conversational.build_system, message, deps, config
    )


@tool
async def delegate_new_search(request: str, config: RunnableConfig) -> str:
    """Délègue une NOUVELLE recherche par filtres exacts, puis persiste la recherche créée."""
    deps = deps_from_config(config)
    deps.events.intention("recherche")
    deps.mode = "recherche"
    answer = await _run_specialist(
        sql_research.sql_research_agent, sql_research.build_system, request, deps, config
    )
    if deps.last_sql:
        await persist_new_research(deps)
    return answer


@tool
async def delegate_refine_search(request: str, config: RunnableConfig) -> str:
    """Délègue l'AFFINAGE de la dernière recherche, puis met à jour la recherche existante."""
    deps = deps_from_config(config)
    deps.events.intention("affinage")
    deps.mode = "affinage"
    deps.previous_sql = _previous_sql(deps)
    prompt = f"Requête SQL précédente : {deps.previous_sql}\nDemande d'affinage : {request}"
    answer = await _run_specialist(
        sql_research.sql_research_agent, sql_research.build_system, prompt, deps, config
    )
    if deps.last_sql:
        await persist_affinage(deps)
    return answer


@tool
async def delegate_semantic_search(subject: str, config: RunnableConfig) -> str:
    """Délègue une recherche par thème/sujet à l'agent sémantique, puis persiste."""
    deps = deps_from_config(config)
    deps.events.intention("recherche_semantique")
    deps.mode = "recherche"
    answer = await _run_specialist(
        semantic_research.semantic_research_agent, semantic_research.build_system, subject, deps, config
    )
    if deps.last_sql:
        await persist_new_research(deps)
    return answer


@tool
async def delegate_correction(message: str, config: RunnableConfig) -> str:
    """Délègue l'enregistrement d'une correction/souvenir à l'agent mémoire."""
    deps = deps_from_config(config)
    deps.events.intention("correction")
    return await _run_specialist(
        memory_spec.memory_agent, memory_spec.build_system, message, deps, config
    )


@tool
async def rename_research(name: str, config: RunnableConfig, research_id: int = 0) -> str:
    """Renomme / sauvegarde la recherche courante (ou celle d'id `research_id`)."""
    deps = deps_from_config(config)
    rid = research_id or deps.research_id
    if not rid:
        return "Aucune recherche courante à sauvegarder."
    await asyncio.to_thread(db_rename_research, rid, name, deps.user_id)
    deps.events.action("rename_research", research_id=rid, new_name=name)
    return f"Recherche sauvegardée sous le nom « {name} »."


@tool
async def delete_research(config: RunnableConfig, research_id: int = 0) -> str:
    """Supprime la recherche courante (ou celle d'id `research_id`)."""
    deps = deps_from_config(config)
    rid = research_id or deps.research_id
    if not rid:
        return "Aucune recherche courante à supprimer."
    await asyncio.to_thread(db_delete_research, rid, deps.user_id)
    deps.events.action("delete_research", research_id=rid)
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


supervisor_agent = create_agent(
    get_agent_model(),
    [
        delegate_conversation,
        delegate_new_search,
        delegate_refine_search,
        delegate_semantic_search,
        delegate_correction,
        rename_research,
        delete_research,
    ],
    system_prompt=_SYSTEM,
)
