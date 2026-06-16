from app.services.intention import classify_intention
from app.services.ollama import call_ollama, stream_ollama
from app.services.database import get_db_schema, execute_select, update_intention, create_research, update_sql, get_sql
from app.services.entity_cache import handle_vocabulary_suggestions
from app.prompts.aide import AIDE_SYSTEM_PROMPT 
from app.prompts.affinage import build_affinage_prompt
from app.prompts.recherche import build_recherche_prompt
from app.prompts.hors_perimetre import HORS_PERIMETRE_SYSTEM_PROMPT
from app.prompts.salutation import SALUTATION_SYSTEM_PROMPT
from app.prompts.entity_extraction import EXTRACTION_PROMPT
import asyncio
import json

# Stream un texte mot par mot avec un délai
async def stream_text(text: str, delay: float = 0.05):
    for chunk in text.split(" "):
        yield chunk + " "
        await asyncio.sleep(delay)

# Retourne un générateur async selon l'intention détectée
async def handle_stream(message: str, user_id: int, historique: list[dict], last_message_id: int, intention: str, research_id_affinage: int):
    if (intention == ''):
        intention = await classify_intention(message, historique)
    print(intention)
    
    update_intention(last_message_id, intention)
    yield json.dumps({ "intention": intention }) + "\n"

    sql = ''
    research_id = ''
    last_id = ''

    if intention == "salutation":
        yield "[STREAM_START]" + "\n"
        prompt = f"\nMessage à traiter: {message}\n"
        async for chunk in stream_ollama(prompt=prompt, system=SALUTATION_SYSTEM_PROMPT):
            yield chunk
    
    elif intention == "aide":
        yield "[STREAM_START]" + "\n"
        async for chunk in stream_ollama(prompt=message, system=AIDE_SYSTEM_PROMPT):
            yield chunk
    
    elif intention == "recherche":
        prompt_message = f"Demande: {message}"
        entities = await call_ollama(prompt=prompt_message, system=EXTRACTION_PROMPT)
        entities_dict = json.loads(entities)  
        has_vocabulary_error, error_message, vocabulary_error = await handle_vocabulary_suggestions(entities_dict)
        if has_vocabulary_error:
            yield json.dumps({ "vocabularyError": vocabulary_error }) + "\n"
            yield "[STREAM_START]" + "\n"
            async for chunk in stream_text(error_message):
                yield chunk
            return
        
        schema = get_db_schema()
        prompt_system = build_recherche_prompt(schema, user_id)
        sql = await call_ollama(prompt=prompt_message, system=prompt_system)
        print(sql)
    
    elif intention == "affinage":
        prompt_message = f"Demande: {message}"
        entities = await call_ollama(prompt=prompt_message, system=EXTRACTION_PROMPT)
        print(entities)
        entities_dict = json.loads(entities)  
        has_vocabulary_error, error_message, vocabulary_error = await handle_vocabulary_suggestions(entities_dict)
        if has_vocabulary_error:
            yield json.dumps({ "intention": intention, "vocabularyError": vocabulary_error }) + "\n"
            yield "[STREAM_START]" + "\n"
            async for chunk in stream_text(error_message):
                yield chunk
            return
        
        schema = get_db_schema()
        last_sql = ''
        if (research_id_affinage != 0):
            last_sql = get_sql(research_id_affinage)
        else:
            last_sql = historique[-2]['sql']

        last_id = historique[-2]['id']
        prompt_sql = build_affinage_prompt(schema, last_sql, user_id, historique)
        sql = await call_ollama(prompt=prompt_sql)
        print(sql)
    
    elif intention == "hors_perimetre":
        yield "[STREAM_START]" + "\n"
        async for chunk in stream_ollama(prompt=message, system=HORS_PERIMETRE_SYSTEM_PROMPT):
            yield chunk
    
    else:
        yield "[STREAM_START]" + "\n"
        async for chunk in stream_text("Je n'ai pas compris votre demande."):
            yield chunk

    if intention in ("recherche", "affinage"):
        try:
            resultats = execute_select(sql, research_id, user_id)
            nb_resultats = len(resultats)

            if intention == "recherche":
                research_id = create_research(user_id, sql)
            else: 
                research_id = update_sql(last_id, sql, research_id_affinage)

            yield json.dumps({ "intention": intention, "generated_sql": sql, "research_id": research_id }) + "\n"
            yield "[STREAM_START]" + "\n"

            if nb_resultats == 0:
                async for chunk in stream_text("Aucun ticket ne correspond à votre recherche."):
                    yield chunk
            else:
                header = ''
                if intention == "recherche":
                    header = f"<p>Résultats de la recherche : {nb_resultats} ticket{'s' if nb_resultats > 1 else ''} trouvé{'s' if nb_resultats > 1 else ''}.</p>"
                else:
                    header = f"<p>La recherche a été modifiée.</p><p>Résultats de la recherche : {nb_resultats} ticket{'s' if nb_resultats > 1 else ''} trouvé{'s' if nb_resultats > 1 else ''}.</p>"
                
                async for chunk in stream_text(header):
                    yield chunk

        except Exception as e:
            yield json.dumps({"intention": intention, "generated_sql": sql, "research_id": '', "error": str(e)}, ensure_ascii=False) + "\n"
            yield f"⚠️ Erreur SQL : {str(e)}"
            #yield "[STREAM_START]" + "\n"
            