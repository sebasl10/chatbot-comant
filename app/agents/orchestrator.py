"""Orchestrateur de streaming (LangGraph) — pont endpoint FastAPI ↔ superviseur.

Produit exactement le même flux que la branche Pydantic AI :
1. lignes JSON d'événements (intention, research, action, correction…),
2. sentinelle ``[STREAM_START]``,
3. réponse en langage naturel du superviseur.

Choix : on exécute le superviseur en une passe (``ainvoke``) — ses outils de
délégation s'exécutent et remplissent ``deps.events`` — puis on draine les
événements avant ``[STREAM_START]`` et on streame la réponse finale mot à mot.
Ce choix garantit l'ordre des événements et évite le filtrage délicat du streaming
token-level à travers des sous-agents imbriqués (repli documenté dans le plan).
"""
import asyncio
import json
from collections.abc import AsyncIterator

from langchain_core.messages import HumanMessage

from app.agents.deps import ChatDeps
from app.agents.supervisor import supervisor_agent
from app.services.events import STREAM_START
from app.services.database import update_intention


def _history_context(historique: list[dict], limit: int = 6) -> str:
    """Résumé compact des derniers messages, injecté dans le prompt du superviseur."""
    if not historique:
        return ""
    lines = []
    for msg in historique[-limit:]:
        role = msg.get("sender_role") or msg.get("role") or "user"
        content = msg.get("content") or msg.get("contenu") or ""
        if content:
            lines.append(f"- {role}: {content}")
    return ("Contexte de conversation (récent) :\n" + "\n".join(lines) + "\n\n") if lines else ""


async def _emit_events(deps: ChatDeps) -> str:
    """Draine les événements, persiste l'intention choisie (compat legacy) et
    renvoie leur sérialisation JSON (une ligne par événement)."""
    events = deps.events.drain()
    for e in events:
        if e["event"] == "intention" and deps.last_message_id:
            try:
                await asyncio.to_thread(update_intention, deps.last_message_id, e["intention"])
            except Exception:
                pass  # la persistance de l'intention ne doit pas casser le flux
    return "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events)


async def _word_stream(text: str, delay: float = 0.02) -> AsyncIterator[str]:
    for chunk in text.split(" "):
        yield chunk + " "
        await asyncio.sleep(delay)


async def run_chat_stream(message: str, deps: ChatDeps) -> AsyncIterator[str]:
    prompt = _history_context(deps.historique) + f"Message de l'utilisateur : {message}"
    config = {"configurable": {"deps": deps}}

    try:
        result = await supervisor_agent.ainvoke({"messages": [HumanMessage(content=prompt)]}, config)
        final = result["messages"][-1].content
        if not isinstance(final, str):
            final = str(final)

        yield await _emit_events(deps)
        yield STREAM_START
        async for word in _word_stream(final):
            yield word
    except Exception as e:  # dégradation propre : on informe le front
        deps.events.error(str(e))
        yield await _emit_events(deps)
        yield STREAM_START
        yield f"⚠️ Une erreur est survenue : {e}"
