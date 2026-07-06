from app.prompts.hybrid_research import HYBRID_RESEARCH_PROMPT, HYBRID_RESEARCH_SQL_PROMPT
from app.services.embedding import embedding_service
from app.services.intention import classify_intention
from app.services.ollama import call_ollama, stream_ollama
from app.services.database import get_db_schema, execute_select, update_intention, create_research, update_sql, get_sql
from app.services.entity_cache import handle_vocabulary_suggestions
from app.services.correction import correction_service
from app.services.memory_md import get_memories
from app.services.chroma_service import get_chroma_service
from app.prompts.aide import AIDE_SYSTEM_PROMPT 
from app.prompts.affinage import build_affinage_prompt
from app.prompts.recherche import build_recherche_prompt
from app.prompts.hors_perimetre import HORS_PERIMETRE_SYSTEM_PROMPT
from app.prompts.salutation import SALUTATION_SYSTEM_PROMPT
from app.prompts.entity_extraction import EXTRACTION_PROMPT
from app.services.verify_memories import verify_sql_against_memories
import asyncio
import json

# Stream un texte mot par mot avec un délai
async def stream_text(text: str, delay: float = 0.05):
    for chunk in text.split(" "):
        yield chunk + " "
        await asyncio.sleep(delay)
        
def clean_json(text: str):
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:].strip()
    if text.startswith("```"):
        text = text[3:].strip()
    if text.endswith("```"):
        text = text[:-3].strip()
    return text

# ── Simple intent handlers ────────────────────────────────────────────────────

SIMPLE_INTENT_PROMPTS = {
    "salutation":     SALUTATION_SYSTEM_PROMPT,
    "aide":           AIDE_SYSTEM_PROMPT,
    "hors_perimetre": HORS_PERIMETRE_SYSTEM_PROMPT,
}

async def stream_simple_intent(message: str, system_prompt: str):
    yield "[STREAM_START]\n"
    async for chunk in stream_ollama(prompt=message, system=system_prompt):
        yield chunk


# ── SQL intent helpers ────────────────────────────────────────────────────────

async def extract_and_validate_entities(message: str):
    """Returns (entities_dict, error_chunks_generator | None)."""
    response = await call_ollama(prompt=f"Demande: {message}", system=EXTRACTION_PROMPT)
    print(f"\n{'─' * 60}\n[ENTITY EXTRACTION RESPONSE]\n{response}\n{'─' * 60}")
    
    response = clean_json(response)
        
    entities_dict = json.loads(response)
    has_error, error_message, vocabulary_error = await handle_vocabulary_suggestions(entities_dict)
    if has_error:
        return entities_dict, (vocabulary_error, error_message)
    return entities_dict, None


async def generate_sql(message: str, intention: str, user_id: int, historique: list[dict], research_id_affinage: int, entities_dict: dict) -> str:
    schema = get_db_schema()
    prompt_message = f"Demande: {message}"

    if intention.startswith("recherche"):
        prompt_message = f"Demande: {message}. Entités qui ont été trouvées dans la requête: {entities_dict}"
        system = build_recherche_prompt(schema, user_id)
        return await call_ollama(prompt=prompt_message, system=system)

    # affinage
    last_sql = get_sql(research_id_affinage) if research_id_affinage != 0 else historique[-2]["sql"]
    system = build_affinage_prompt(schema, last_sql, user_id, historique)
    return await call_ollama(prompt=system)


async def persist_and_stream_results(sql: str, intention: str, user_id: int, historique: list[dict], research_id_affinage: int):
    last_id = historique[-2]["id"] if intention == "affinage" else None
    resultats = execute_select(sql, "", user_id)
    nb = len(resultats)

    if intention in ("recherche", "recherche_semantique", "recherche_hybride"):
        research_id = create_research(user_id, sql)
    else:
        research_id = update_sql(last_id, sql, research_id_affinage)

    yield json.dumps({"intention": intention, "generated_sql": sql, "research_id": research_id}) + "\n"
    yield "[STREAM_START]\n"

    if nb == 0:
        async for chunk in stream_text("Aucun ticket ne correspond à votre recherche."):
            yield chunk
        return

    plural = lambda n: "s" if n > 1 else ""
    header = (
        f"<p>Résultats de la recherche : {nb} ticket{plural(nb)} trouvé{plural(nb)}.</p>"
        if intention in ("recherche", "recherche_semantique")
        else f"<p>La recherche a été modifiée.</p>"
             f"<p>Résultats de la recherche : {nb} ticket{plural(nb)} trouvé{plural(nb)}.</p>"
    )
    async for chunk in stream_text(header):
        yield chunk

async def handle_hybrid_research(message, intention, user_id, historique, research_id_affinage):
    response = await call_ollama(prompt=f"Message: {message}", system=HYBRID_RESEARCH_PROMPT)
    response = json.loads(clean_json(response))
    requete_filtres = response['requete_filtres']
    requete_semantique = response['requete_semantique']
    
    # Extraction et validation des entités UNIQUEMENT pour requete_filtres
    entities_dict, vocab_error = await extract_and_validate_entities(requete_filtres)
    if vocab_error:
        return None, vocab_error
    
    # Récupérer les mémoires pour la recherche sémantique
    expand_vocabulary_memories = await get_memories(user_id, "expand_vocabulary")
    
    sql_filtres = await generate_sql(requete_filtres, intention, user_id, historique, research_id_affinage, entities_dict)
    sql_semantique = await embedding_service(requete_semantique, expand_vocabulary_memories, user_id)
        
    prompt = f"Première requête SQL: {sql_filtres}\n Deuxième requête SQL: {sql_semantique}"
    sql_final = await call_ollama(prompt=prompt, system=HYBRID_RESEARCH_SQL_PROMPT)
    print(f"\n{'─' * 60}\n[SQL FINAL HYBRID]\n{sql_final}\n{'─' * 60}\n")
    return sql_final, None
    
# ── Main entry point ──────────────────────────────────────────────────────────

async def handle_stream(message: str, user_id: int, historique: list[dict],
                        last_message_id: int, intention: str, research_id_affinage: int):
    """ print(historique)
    print(len(historique)) """
    if not intention:
        intention = await classify_intention(message)
    print(f"\n[DEBUG] Detected intention: {intention}\n")

    update_intention(last_message_id, intention)
    yield json.dumps({"intention": intention}) + "\n"

    # ── Simple intents ──────────────────────────────────────────────────────
    if intention in SIMPLE_INTENT_PROMPTS:
        async for chunk in stream_simple_intent(message, SIMPLE_INTENT_PROMPTS[intention]):
            yield chunk
        return
    
    if intention == "correction":
        correction_data = await correction_service(message, historique, user_id)
        print(f"\n{'─' * 60}\n[CORRECTION ANALYSIS]\n{json.dumps(correction_data, indent=2, ensure_ascii=False)}\n{'─' * 60}")
        
        # Retourner le résultat de la correction
        yield json.dumps({"intention": intention, "correction_type": correction_data["type"], "memory": correction_data["memory"]}) + "\n"
        yield "[STREAM_START]\n"
        async for chunk in stream_text(f"J'ai enregistré votre correction : <br/>{correction_data['memory']}"):
            yield chunk
        return
    
    # ── Semantic research intent ────────────────────────────────────────────
    if intention == "recherche_semantique":
        expand_vocabulary_memories = await get_memories(user_id, "expand_vocabulary")
        print(f"\n{'─' * 60}\n[EXPAND VOCABULARY MEMORIES]\n{expand_vocabulary_memories}\n{'─' * 60}\n")
        
        sql = await embedding_service(message, expand_vocabulary_memories, user_id)
        async for chunk in persist_and_stream_results(sql, intention, user_id, historique, research_id_affinage):
            yield chunk
        return
    
    # ── Hybrid research intent  ────────────────
    if intention == "recherche_hybride":
        sql, vocab_error = await handle_hybrid_research(message, intention, user_id, historique, research_id_affinage)
        if vocab_error:
            vocabulary_error, error_message = vocab_error
            yield json.dumps({"intention": intention, "vocabularyError": vocabulary_error}) + "\n"
            yield "[STREAM_START]\n"
            async for chunk in stream_text(error_message):
                yield chunk
            return
        try:
            async for chunk in persist_and_stream_results(sql, intention, user_id, historique, research_id_affinage):
                yield chunk
        except Exception as e:
            yield json.dumps({"intention": intention, "generated_sql": sql, "research_id": "", "error": str(e)}, ensure_ascii=False) + "\n"
            yield f"⚠️ Erreur SQL : {e}"
        return
        
    # ── Unknown intent ──────────────────────────────────────────────────────
    if intention not in ("recherche", "affinage"):
        yield "[STREAM_START]\n"
        async for chunk in stream_text("Je n'ai pas compris votre demande."):
            yield chunk
        return

    # ── SQL intents (recherche / affinage) ──────────────────────────────────
    entities_dict, vocab_error = await extract_and_validate_entities(message)
    if vocab_error:
        vocabulary_error, error_message = vocab_error
        yield json.dumps({"intention": intention, "vocabularyError": vocabulary_error}) + "\n"
        yield "[STREAM_START]\n"
        async for chunk in stream_text(error_message):
            yield chunk
        return

    try:
        # Récupérer les corrections SQL mémorisées pour cet utilisateur
        correction_sql_memories = await get_memories(user_id, "correction_sql")
        """ chroma_service = get_chroma_service()
        correction_sql_memories = chroma_service.search_memories("correction", "message", where={"user_id": user_id})  """
        print(f"\n{'─' * 60}\n[CORRECTION SQL MEMORIES]\n{correction_sql_memories}\n{'─' * 60}\n")
        
        sql = await generate_sql(message, intention, user_id, historique, research_id_affinage, entities_dict)
        print(f"\n{'─' * 60}\n[SQL INITIAL]\n{sql}\n{'─' * 60}\n")

        if (correction_sql_memories != ''):
            sql = await verify_sql_against_memories(message, sql, correction_sql_memories, user_id)
            print(f"\n{'─' * 60}\n[SQL APRES VERIFICATION]\n{sql}\n{'─' * 60}\n")

        async for chunk in persist_and_stream_results(sql, intention, user_id, historique, research_id_affinage):
            yield chunk
        
    except Exception as e:
        yield json.dumps({"intention": intention, "generated_sql": sql, "research_id": "", "error": str(e)}, ensure_ascii=False) + "\n"
        yield f"⚠️ Erreur SQL : {e}"