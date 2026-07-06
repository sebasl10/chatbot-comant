"""
Orchestrateur de streaming — pont entre l'endpoint FastAPI et le superviseur.

Produit le flux attendu par le front :
1. des lignes JSON d'événements (intention, research, action, correction…),
2. la sentinelle ``[STREAM_START]``,
3. la réponse en langage naturel du superviseur, streamée en token/delta.

Les événements sont accumulés dans ``deps.events`` pendant l'exécution des outils
de délégation (qui ont lieu AVANT la génération du texte final), puis drainés
juste avant ``[STREAM_START]``.
"""
import asyncio
import json
from collections.abc import AsyncIterator

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
                pass 
    return "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events)


async def run_chat_stream(message: str, deps: ChatDeps) -> AsyncIterator[str]:
    prompt = _history_context(deps.historique) + f"Message de l'utilisateur : {message}"

    try:
        async with supervisor_agent.run_stream(prompt, deps=deps) as result:
            #print(f"\n{'─' * 60}\n[SUPERVISOR AGENT RESULT]\n{result}\n{'─' * 60}\n")
            yield await _emit_events(deps)
            yield STREAM_START
            async for delta in result.stream_text(delta=True):
                yield delta
        
        tail = await _emit_events(deps)
        if tail:
            yield tail
    except Exception as e:  
        deps.events.error(str(e))
        yield deps.events.serialize()
        yield STREAM_START
        yield f"⚠️ Une erreur est survenue : {e}"
