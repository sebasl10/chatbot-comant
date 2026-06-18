import asyncio
import json
import sys
import os
import time
import httpx
from fastapi import HTTPException
from app.config import settings

# Ajouter le parent directory au path pour les imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.ollama import call_ollama
from app.services.database import get_db_schema, execute_select
from app.prompts.recherche import build_recherche_prompt


LMSTUDIO_URL = "http://192.168.69.42:1234/chat"
OLLAMA_URL = "http://localhost:11434/api/generate"

async def run_tests():
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
    
    # Enregistrer le temps de départ
    start_time = time.time()
    
    print(f"Démarrage des tests... {total_tests} tests à exécuter.\n")
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
            payload = {
                "model": settings.model_ia,
                "prompt": f"Demande: {user_query}",
                "stream": False,
                "system": system_prompt
            }
            
            async with httpx.AsyncClient(timeout=60.0) as client:
                try:
                    res = await client.post(settings.ollama_url, json=payload)
                    res.raise_for_status() # Raises an exception if status code between 400 and 599 (HTTP error)
                except httpx.ConnectError:
                    raise HTTPException(status_code=503, detail="Ollama is not running on localhost:11434")
                except httpx.HTTPStatusError as e:
                    raise HTTPException(status_code=502, detail=f"Ollama error: {e.response.text}")
            
            print(res)
            generated_sql = res['response']
            
            # Nettoyer la réponse (supprimer les markdown blocks si présents)
            generated_sql = generated_sql.strip()
            if generated_sql.startswith("```sql"):
                generated_sql = generated_sql[6:].strip()
            if generated_sql.startswith("```"):
                generated_sql = generated_sql[3:].strip()
            if generated_sql.endswith("```"):
                generated_sql = generated_sql[:-3].strip()
            
            print(f"  → SQL générée: {generated_sql}")
            print(f"Load duration: {res["load_duration"]} ")
            print(f"Prompt eval duration: {res["prompt_eval_duration"]} ")
            print(f"Eval duration: {res["eval_duration"]} ")
            
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

async def test_nb_tokens():
    print("Executing query...")
    user_query = "cherche les tickets créés par mwu, assignés à sls"
    user_id = 5
    schema = get_db_schema()
    system_prompt = build_recherche_prompt(schema, user_id)
    payload = {
        "model": settings.model_ia,
        "prompt": f"Demande: {user_query}",
        "stream": False,
        "system": system_prompt
    }
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            res = await client.post(settings.ollama_url, json=payload)
            res.raise_for_status() # Raises an exception if status code between 400 and 599 (HTTP error)
        except httpx.ConnectError:
            raise HTTPException(status_code=503, detail="Ollama is not running on localhost:11434")
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=502, detail=f"Ollama error: {e.response.text}")
    
    print(f"Input tokens: {res.json()['prompt_eval_count']}")
    print(f"Output tokens: {res.json()['eval_count']}")

if __name__ == "__main__":
    asyncio.run(run_tests())
