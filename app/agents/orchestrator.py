"""
Orchestrateur de streaming — pont entre l'endpoint FastAPI et le superviseur.

Produit le flux attendu par le front :
1. des lignes JSON d'événements (intention, research, action, correction…),
2. la sentinelle ``[STREAM_START]``,
3. la réponse en langage naturel du superviseur, streamée en token/delta.

Les événements précoces (early events) sont envoyés immédiatement au front
pour permettre l'affichage "recherche en cours" avant que la recherche ne commence.

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
from app.agents.util.output_guard import looks_like_leaked_tool_call


async def _emit_events(deps: ChatDeps) -> str:
    """
    Draine les événements, persiste l'intention choisie (compat legacy) et
    renvoie leur sérialisation JSON (une ligne par événement).
    
    Les événements d'intention qui ont été envoyés comme early events ne sont PAS inclus
    dans le retour, car ils sont déjà envoyés au front.
    """
    # Sauvegarder les early intentions AVANT de drainer (car drain() vide le set)
    early_intentions = set(deps.events._early_emitted_intentions)
    events = deps.events.drain()
    for e in events:
        if e["event"] == "intention" and deps.last_message_id:
            try:
                await asyncio.to_thread(update_intention, deps.last_message_id, e["intention"])
            except Exception:
                pass 
    # Filtrer les intentions qui ont été envoyées comme early events
    filtered_events = [
        e for e in events 
        if not (e["event"] == "intention" and e["intention"] in early_intentions)
    ]
    return "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in filtered_events)


async def run_chat_stream(message: str, deps: ChatDeps) -> AsyncIterator[str]:
    user_prompt_with_few_shot = build_user_prompt_with_few_shot(message)
    prompt = _history_context(deps.historique) + user_prompt_with_few_shot

    early_events_queue = asyncio.Queue()

    def early_callback(event: dict) -> None:
        early_events_queue.put_nowait(event)

    deps.events.set_early_callback(early_callback)

    try:
        # Lancer le supervisor dans une tâche asynchrone pour permettre
        # de traiter les early events pendant son exécution
        supervisor_task = asyncio.create_task(
            supervisor_agent.run(prompt, deps=deps)
        )

        # Traiter les early events au fur et à mesure qu'ils arrivent
        while not supervisor_task.done():
            try:
                event = await asyncio.wait_for(
                    early_events_queue.get(),
                    timeout=0.01
                )
                yield json.dumps(event, ensure_ascii=False) + "\n"
            except asyncio.TimeoutError:
                await asyncio.sleep(0)

        result = await supervisor_task

        # Envoyer les événements normaux accumulés (intention, research, etc.)
        yield await _emit_events(deps)
        yield STREAM_START
        
        output = result.output
        if looks_like_leaked_tool_call(output):
            print(f"[GUARD] Sortie ressemblant à un appel d'outil non exécuté, filtrée : {output!r}")
            output = (
                "Désolé, une erreur technique est survenue pendant le traitement de votre "
                "demande. Pouvez-vous reformuler votre message ?"
            )
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
    finally:
        deps.events.set_early_callback(None)
