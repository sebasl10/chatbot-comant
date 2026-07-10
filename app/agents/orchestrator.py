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
from app.agents.util.history_utils import _history_context
from app.agents.supervisor import supervisor_agent
from app.services.events import STREAM_START
from app.services.database import update_intention
from app.agents.prompts.agent_supervisor import build_user_prompt_with_few_shot

async def _emit_events(deps: ChatDeps) -> str:
    """
    Draine les événements, persiste l'intention choisie (compat legacy) et
    renvoie leur sérialisation JSON (une ligne par événement).
    """
    events = deps.events.drain()
    for e in events:
        if e["event"] == "intention" and deps.last_message_id:
            try:
                await asyncio.to_thread(update_intention, deps.last_message_id, e["intention"])
            except Exception:
                pass 
    return "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events)


async def run_chat_stream(message: str, deps: ChatDeps) -> AsyncIterator[str]:
    user_prompt_with_few_shot = build_user_prompt_with_few_shot(message)
    prompt = _history_context(deps.historique) + user_prompt_with_few_shot

    try:
        result = await supervisor_agent.run(prompt, deps=deps)
        yield await _emit_events(deps)
        yield STREAM_START
        
        output = result.output
        for chunk in output.split(" "):
            yield chunk + " "
            await asyncio.sleep(0.05)
        
        tail = await _emit_events(deps)
        if tail:
            yield tail
    except Exception as e:  
        deps.events.error(str(e))
        yield deps.events.serialize()
        yield STREAM_START
        yield f"⚠️ Une erreur est survenue : {e}"
