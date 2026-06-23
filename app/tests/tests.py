import asyncio
import json
import sys
import os
import time
import httpx
from fastapi import HTTPException
from app.config import settings
from app.services.database import get_db_schema, execute_select
from app.prompts.recherche import build_recherche_prompt
from app.prompts.entity_extraction import EXTRACTION_PROMPT
from app.prompts.intention import INTENT_SYSTEM_PROMPT

# Ajouter le parent directory au path pour les imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

async def call_llm_provider(provider: str, model: str, prompt: str, system_prompt: str, stream: bool = False):
    """
    Generic function to call either Ollama or LMStudio API.
    """
    
    if provider == "ollama":
        url = settings.ollama_url
        payload = {
            "model": model,
            "prompt": prompt,
            "system": system_prompt,
            "stream": stream,
        }
        headers = {"Content-Type": "application/json"}
        
    elif provider == "lmstudio":
        url = settings.lmstudio_url
        payload = {
            "model": model,
            "input": prompt,
            "system_prompt": system_prompt,
            "stream": stream
        }
        headers = {
            "Content-Type": "application/json"
        }
    else:
        raise ValueError(f"Unknown provider: {provider}. Use {"ollama"} or {"lmstudio"}")
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            return response.json()
        except httpx.ConnectError as e:
            raise HTTPException(
                status_code=503, 
                detail=f"{provider.capitalize()} is not running or unreachable: {e}"
            )
        except httpx.HTTPStatusError as e:
            error_detail = f"{provider.capitalize()} error: {e.response.text}"
            raise HTTPException(status_code=502, detail=error_detail)


def extract_sql_from_response(response_data: dict, provider: str) -> str:
    """
    Extract SQL query from provider response.
    """
    
    if provider == "ollama":
        generated_sql = response_data.get("response", "")
        
    elif provider == "lmstudio":
        output_items = response_data.get("output", [])
        if output_items:
            for item in output_items:
                if item.get("type") == "message":
                    generated_sql = item.get("content", "")
                    break
            else:
                generated_sql = output_items[0].get("content", "")
        else:
            generated_sql = ""
    else:
        raise ValueError(f"Unknown provider: {provider}")
    
    generated_sql = generated_sql.strip()
    if generated_sql.startswith("```sql"):
        generated_sql = generated_sql[6:].strip()
    if generated_sql.startswith("```"):
        generated_sql = generated_sql[3:].strip()
    if generated_sql.endswith("```"):
        generated_sql = generated_sql[:-3].strip()
    
    return generated_sql


def get_provider_stats(response_data: dict, provider: str) -> dict:
    """
    Extract statistics from provider response.
    """
    
    if provider == "ollama":
        return {
            "load_duration": response_data.get("load_duration", 0),
            "prompt_eval_duration": response_data.get("prompt_eval_duration", 0),
            "eval_duration": response_data.get("eval_duration", 0),
            "input_tokens": response_data.get("prompt_eval_count", 0),
            "output_tokens": response_data.get("eval_count", 0)
        }
    elif provider == "lmstudio":
        stats = response_data.get("stats", {})
        return {
            "input_tokens": stats.get("input_tokens", 0),
            "output_tokens": stats.get("total_output_tokens", 0),
            "reasoning_tokens": stats.get("reasoning_output_tokens", 0),
            "tokens_per_second": stats.get("tokens_per_second", 0),
            "time_to_first_token": stats.get("time_to_first_token_seconds", 0),
            "model_load_time": stats.get("model_load_time_seconds", 0)
        }
    else:
        return {}


async def run_tests(provider: str = "ollama"):
    """
    Fonction principale qui exécute les tests de requêtes SQL.
    Lit le fichier requetes_test.json, envoie chaque requête utilisateur au modèle IA,
    exécute les requêtes SQL générée et de référence, puis compare les résultats.
    """
    
    test_file_path = os.path.join(os.path.dirname(__file__), "requetes_test.json")
    
    try:
        with open(test_file_path, 'r', encoding='utf-8') as f:
            test_cases = json.load(f)
    except FileNotFoundError:
        print(f"Erreur: Le fichier {test_file_path} n'existe pas.")
        return
    except json.JSONDecodeError as e:
        print(f"Erreur de parsing JSON: {e}")
        return
    
    try:
        schema = get_db_schema()
    except Exception as e:
        print(f"Erreur lors de la récupération du schéma: {e}")
        return
    
    total_tests = len(test_cases)
    passed_tests = 0
    failed_tests = 0
    
    start_time = time.time()
    
    print(f"Démarrage des tests avec {provider}... {total_tests} tests à exécuter.\n")
    print("=" * 100)
    
    user_id = 5
    
    for i, test_case in enumerate(test_cases, 1):
        user_query = test_case.get("user", "")
        correct_sql = test_case.get("correct_sql", "")
        
        print(f"\nTest {i}/{total_tests}")
        print(f"Requête utilisateur: {user_query}")
        print(f"SQL attendue: {correct_sql}\n")
        
        try:
            # Étape 1: Générer la requête SQL via le modèle IA
            system_prompt = build_recherche_prompt(schema, user_id)
            if provider == "ollama":
                model = settings.model_ia
            else:
                model = settings.model_ia_lmstudio
            
            response_entities = await call_llm_provider(
                provider=provider,
                model=model,
                prompt=f"Demande: {user_query}",
                system_prompt=EXTRACTION_PROMPT,
                stream=False
            )
            print(response_entities['response'])
            entities_dict = json.loads(response_entities['response'])
            
            response_data = await call_llm_provider(
                provider=provider,
                model=model,
                prompt=f"Demande: {user_query}. Entités qui ont été trouvées dans la requête: {entities_dict}",
                system_prompt=system_prompt,
                stream=False
            )
            
            generated_sql = extract_sql_from_response(response_data, provider)
            stats = get_provider_stats(response_data, provider)
            
            print(f"  → SQL générée: {generated_sql}")
            if provider == "ollama":
                print(f"Load duration: {stats.get('load_duration', 'N/A')} ")
                print(f"Prompt eval duration: {stats.get('prompt_eval_duration', 'N/A')} ")
                print(f"Eval duration: {stats.get('eval_duration', 'N/A')} ")
            elif provider == "lmstudio":
                print(f"Input tokens: {stats.get('input_tokens', 'N/A')} ")
                print(f"Output tokens: {stats.get('output_tokens', 'N/A')} ")
                print(f"Reasoning tokens: {stats.get("reasoning_output_tokens", 'N/A')} ")
                print(f"Tokens per second: {stats.get('tokens_per_second', 'N/A')} ")
                print(f"Time to first token: {stats.get('time_to_first_token', 'N/A')} ")
            
            # Étape 2: Exécuter la requête générée
            try:
                generated_results = execute_select(generated_sql, 0, 0)
                generated_count = len(generated_results)
                generated_ids = set(str(row.get('id', '')) for row in generated_results)
                print(f"  → Résultats générés: {generated_count} lignes, IDs: {sorted(generated_ids)[:5]}{'...' if len(generated_ids) > 5 else ''}")
            except Exception as e:
                print(f"  → ❌ ERREUR lors de l'exécution de la requête générée: {e}")
                failed_tests += 1
                continue
            
            # Étape 3: Exécuter la requête de référence
            try:
                correct_results = execute_select(correct_sql, 0, 0)
                correct_count = len(correct_results)
                correct_ids = set(str(row.get('id', '')) for row in correct_results)
                print(f"  → Résultats corrects: {correct_count} lignes, IDs: {sorted(correct_ids)[:5]}{'...' if len(correct_ids) > 5 else ''}")
            except Exception as e:
                print(f"  → ❌ ERREUR lors de l'exécution de la requête de référence: {e}")
                failed_tests += 1
                continue
            
            # Étape 4: Comparaison des résultats
            print("  → Comparaison des résultats...")
            count_match = generated_count == correct_count
            ids_match = generated_ids == correct_ids
            
            if count_match and ids_match:
                print(f"  ✅ TEST PASSED - Nombre de lignes: {generated_count}, IDs correspondent")
                passed_tests += 1
            else:
                print(f"  ❌ TEST FAILED")
                if not count_match:
                    print(f"     - Nombre de lignes différent: généré={generated_count}, attendu={correct_count}")
                if not ids_match:
                    missing_ids = correct_ids - generated_ids
                    extra_ids = generated_ids - correct_ids
                    if missing_ids:
                        print(f"     - IDs manquants: {sorted(missing_ids)[:5]}{'...' if len(missing_ids) > 5 else ''}")
                    if extra_ids:
                        print(f"     - IDs en trop: {sorted(extra_ids)[:5]}{'...' if len(extra_ids) > 5 else ''}")
                failed_tests += 1
                
        except Exception as e:
            print(f"  ❌ ERREUR INATTENDUE: {e}")
            import traceback
            traceback.print_exc()
            failed_tests += 1
    
    print("\n" + "=" * 100)
    print("\nSTATISTIQUES FINALES")
    print("=" * 100)
    print(f"Fournisseur: {provider}")
    print(f"Total des tests: {total_tests}")
    print(f"Tests passés: {passed_tests}")
    print(f"Tests échoués: {failed_tests}")
    print(f"Taux de réussite: {(passed_tests / total_tests * 100):.2f}%")
    
    # Calculer et afficher le temps écoulé
    elapsed_time = time.time() - start_time
    print(f"Temps d'exécution: {elapsed_time:.2f} secondes")
    
    if failed_tests > 0:
        print(f"\n⚠️  {failed_tests} test(s) ont échoué. Voir les détails ci-dessus.")
    else:
        print("\n✅ Tous les tests ont réussi!")


async def test_nb_tokens(provider: str = "ollama"):
    print(f"Executing query with {provider}...")
    user_query = "cherche les tickets créés par mwu, assignés à sls"
    user_id = 5
    schema = get_db_schema()
    system_prompt = build_recherche_prompt(schema, user_id)
    
    if provider == "ollama":
        model = settings.model_ia
    else:
        model = settings.model_ia_lmstudio
    
    response_data = await call_llm_provider(
        provider=provider,
        model=model,
        prompt=user_query,
        system_prompt=system_prompt,
        stream=False
    )
    
    stats = get_provider_stats(response_data, provider)
    
    print(extract_sql_from_response(response_data, provider))
    print(stats)


def extract_intention_from_response(response_data: dict, provider: str) -> str:
    """
    Extract intention from provider response.
    """
    if provider == "ollama":
        intention = response_data.get("response", "").strip().lower()
    elif provider == "lmstudio":
        output_items = response_data.get("output", [])
        if output_items:
            for item in output_items:
                if item.get("type") == "message":
                    intention = item.get("content", "").strip().lower()
                    break
            else:
                intention = output_items[0].get("content", "").strip().lower()
        else:
            intention = ""
    else:
        raise ValueError(f"Unknown provider: {provider}")
    
    return intention


async def run_intention_tests(provider: str = "ollama"):
    """
    Fonction qui exécute les tests d'identification d'intention.
    Lit le fichier intentions_test.json, envoie chaque message utilisateur au modèle IA,
    et compare l'intention retournée avec l'intention attendue.
    """
    
    test_file_path = os.path.join(os.path.dirname(__file__), "intentions_test.json")
    
    try:
        with open(test_file_path, 'r', encoding='utf-8') as f:
            test_cases = json.load(f)
    except FileNotFoundError:
        print(f"Erreur: Le fichier {test_file_path} n'existe pas.")
        return
    except json.JSONDecodeError as e:
        print(f"Erreur de parsing JSON: {e}")
        return
    
    total_tests = len(test_cases)
    passed_tests = 0
    failed_tests = 0
    
    start_time = time.time()
    
    print(f"Démarrage des tests d'intention avec {provider}... {total_tests} tests à exécuter.\n")
    print("=" * 100)
    
    if provider == "ollama":
        model = settings.model_ia
    else:
        model = settings.model_ia_lmstudio
    
    for i, test_case in enumerate(test_cases, 1):
        user_message = test_case.get("user", "")
        correct_intention = test_case.get("intention", "").lower()
        
        print(f"\nTest {i}/{total_tests}")
        print(f"Message utilisateur: {user_message}")
        print(f"Intention attendue: {correct_intention}\n")
        
        try:
            # Appeler le modèle IA
            response_data = await call_llm_provider(
                provider=provider,
                model=model,
                prompt=f"Message à classifier: {user_message}\n", 
                system_prompt=INTENT_SYSTEM_PROMPT,
                stream=False
            )
            
            # Extraire l'intention de la réponse
            generated_intention = extract_intention_from_response(response_data, provider)
            stats = get_provider_stats(response_data, provider)
            
            print(f"  → Intention générée: {generated_intention}")
            
            # Afficher les statistiques
            if provider == "ollama":
                print(f"  Load duration: {stats.get('load_duration', 'N/A')}")
                print(f"  Prompt eval duration: {stats.get('prompt_eval_duration', 'N/A')}")
                print(f"  Eval duration: {stats.get('eval_duration', 'N/A')}")
            elif provider == "lmstudio":
                print(f"  Input tokens: {stats.get('input_tokens', 'N/A')}")
                print(f"  Output tokens: {stats.get('output_tokens', 'N/A')}")
                print(f"  Reasoning tokens: {stats.get('reasoning_output_tokens', 'N/A')}")
                print(f"  Tokens per second: {stats.get('tokens_per_second', 'N/A')}")
            
            # Comparaison
            if generated_intention == correct_intention:
                print(f"  ✅ TEST PASSED")
                passed_tests += 1
            else:
                print(f"  ❌ TEST FAILED - Attendu: {correct_intention}, Obtenu: {generated_intention}")
                failed_tests += 1
                
        except Exception as e:
            print(f"  ❌ ERREUR INATTENDUE: {e}")
            import traceback
            traceback.print_exc()
            failed_tests += 1
    
    print("\n" + "=" * 100)
    print("\nSTATISTIQUES FINALES")
    print("=" * 100)
    print(f"Fournisseur: {provider}")
    print(f"Total des tests: {total_tests}")
    print(f"Tests passés: {passed_tests}")
    print(f"Tests échoués: {failed_tests}")
    print(f"Taux de réussite: {(passed_tests / total_tests * 100):.2f}%")
    
    # Calculer et afficher le temps écoulé
    elapsed_time = time.time() - start_time
    print(f"Temps d'exécution: {elapsed_time:.2f} secondes")
    
    if failed_tests > 0:
        print(f"\n⚠️  {failed_tests} test(s) ont échoué. Voir les détails ci-dessus.")
    else:
        print("\n✅ Tous les tests ont réussi!")

if __name__ == "__main__":
    provider = "ollama"
    test_type = "sql" 
    
    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()
        if arg in ["ollama", "lmstudio"]:
            provider = arg
        elif arg in ["intentions", "intention"]:
            test_type = "intention"
        elif arg in ["sql", "requetes"]:
            test_type = "sql"
        else:
            print(f"Warning: Unknown argument '{arg}'. Using defaults: provider={provider}, test_type={test_type}")
    
    if len(sys.argv) > 2:
        arg2 = sys.argv[2].lower()
        if arg2 in ["ollama", "lmstudio"]:
            provider = arg2
        elif arg2 in ["intentions", "intention"]:
            test_type = "intention"
        elif arg2 in ["sql", "requetes"]:
            test_type = "sql"
    
    if test_type == "intention":
        asyncio.run(run_intention_tests(provider=provider))
    else:
        asyncio.run(run_tests(provider=provider))
