"""
Initialisation de la collection Chroma supervisor_actions avec des exemples de base.

Ce script crée la collection supervisor_actions et y ajoute des exemples initiaux
pour aider l'agent supervisor à déterminer quelle action entreprendre en fonction
de la requête de l'utilisateur.

Usage :
    python -m app.scripts.init_supervisor_actions

Exemples ajoutés :
- Requêtes de recherche exacte (SQL) -> delegate_new_research
- Requêtes de recherche sémantique -> delegate_semantic_search
- Requêtes de conversation -> delegate_conversation
- Requêtes de correction/mémoire -> delegate_correction
- Requêtes d'affinage -> delegate_refine_search
"""

import asyncio
from app.services.vectorstore import (
    supervisor_actions_collection,
    SUPERVISOR_ACTIONS
)
from app.config import settings
import uuid
from datetime import datetime

# Exemples de base pour l'agent supervisor
SUPERVISOR_EXAMPLES = [
    # Recherche exacte (SQL)
    {
        "user_query": "Cherche les tickets associés au client PTC",
        "action": "delegate_new_research",
    },
    {
        "user_query": "Trouve tous les tickets avec le statut 'En cours'",
        "action": "delegate_new_research",
    },
    {
        "user_query": "Liste les tickets de haute priorité créés cette semaine",
        "action": "delegate_new_research",
    },
    {
        "user_query": "Montre-moi les tickets assignés à dba",
        "action": "delegate_new_research",
    },
    
    # Recherche sémantique
    {
        "user_query": "Cherche les tickets qui parlent d'embeddings",
        "action": "delegate_semantic_search",
    },
    {
        "user_query": "Trouve des tickets concernant l'apprentissage automatique",
        "action": "delegate_semantic_search",
    },
    {
        "user_query": "Quels tickets traitent de l'IA générative ?",
        "action": "delegate_semantic_search",
    },
    {
        "user_query": "Donne-moi les tickets qui parlent d'annotations 3d",
        "action": "delegate_semantic_search",
    },
    
    # Affinage de recherche
    {
        "user_query": "Filtre la recherche précédente pour ne garder que les tickets urgents",
        "action": "delegate_refine_search",
    },
    {
        "user_query": "Ajoute un filtre pour exclure les tickets ouverts",
        "action": "delegate_refine_search",
    },
    {
        "user_query": "Modifie la recherche pour inclure seulement les tickets de 2024",
        "action": "delegate_refine_search",
    },
    
    # Conversation
    {
        "user_query": "Bonjour, comment ça va ?",
        "action": "delegate_conversation",
    },
    {
        "user_query": "Merci pour ton aide",
        "action": "delegate_conversation",
    },
    {
        "user_query": "Peux-tu m'expliquer comment fonctionne ce système ?",
        "action": "delegate_conversation",
    },
    {
        "user_query": "Quelle est la météo aujourd'hui ?",
        "action": "delegate_conversation",
    },
    
    # Mémoire/Correction
    {
        "user_query": "Tu t'es trompé, tu n'as pas utilisé les champs corrects pour construire la requête SQL",
        "action": "delegate_correction",
    },
    {
        "user_query": "Ne rajoute jamais de points virgule à la fin des requêtes SQL",
        "action": "delegate_correction",
    },
]


async def init_collection():
    """Initialise la collection et ajoute les exemples de base."""
    print("=" * 70)
    print("  Initialisation de la collection supervisor_actions")
    print("=" * 70)
    print(f"  URL Chroma: {settings.chroma_http_url}")
    print()

    # Vérifier si la collection existe déjà
    collection = await supervisor_actions_collection()
    count = await collection.count()

    if count > 0:
        print(f"  ⚠️  La collection existe déjà avec {count} exemples.")
        response = input("  Voulez-vous ajouter les exemples manquants ? (y/n): ").strip().lower()
        if response != 'y':
            print("  ❌ Opération annulée.")
            return
        print()
    else:
        print("  ✅ Création d'une nouvelle collection.")
        print()
    
    # Ajouter les exemples
    added_count = 0
    existing_queries = set()
    
    # Récupérer les requêtes existantes pour éviter les doublons
    if count > 0:
        res = await collection.get(include=["documents"])
        existing_queries = set(res.get("documents", []))

    for example in SUPERVISOR_EXAMPLES:
        if example["user_query"] in existing_queries:
            print(f"  ⏭️  Exemple déjà présent: '{example['user_query']}'")
            continue

        doc_id = str(uuid.uuid4())
        now = datetime.now().isoformat()

        metadata = {
            "action": example["action"],
            "type": "supervisor_example",
            "created_at": now,
            "updated_at": now,
        }

        await collection.add(
            ids=[doc_id],
            documents=[example["user_query"]],
            metadatas=[metadata]
        )

        print(f"  ✅ Ajouté: '{example['user_query']}' -> {example['action']}")
        added_count += 1

    print()
    print(f"  ✅ {added_count} exemples ajoutés avec succès.")
    print(f"  Total dans la collection: {await collection.count()}")


async def list_examples():
    """Liste tous les exemples actuels."""
    collection = await supervisor_actions_collection()
    count = await collection.count()

    print("=" * 70)
    print(f"  Liste des exemples de supervision ({count} au total)")
    print("=" * 70)

    if count == 0:
        print("  Aucun exemple trouvé.")
        return

    res = await collection.get(include=["documents", "metadatas"])
    
    ids = res.get("ids", [])
    documents = res.get("documents", [])
    metadatas = res.get("metadatas", [])
    
    for i, (doc_id, doc, meta) in enumerate(zip(ids, documents, metadatas), 1):
        action = meta.get("action", "inconnu")
        description = meta.get("description", "")
        
        print(f"\n  {i}. ID: {doc_id}")
        print(f"     Requête: {doc}")
        print(f"     Action: {action}")
        if description:
            print(f"     Description: {description}")


async def clear_collection():
    """Supprime tous les exemples de la collection."""
    print("=" * 70)
    print("  ⚠️  ATTENTION: Suppression de tous les exemples de supervision")
    print("=" * 70)

    response = input("  Êtes-vous sûr ? (y/n): ").strip().lower()
    if response != 'y':
        print("  ❌ Opération annulée.")
        return

    collection = await supervisor_actions_collection()
    all_res = await collection.get(include=["ids"])
    all_ids = all_res.get("ids", [])

    if all_ids:
        await collection.delete(ids=all_ids)
        print(f"  ✅ {len(all_ids)} exemples supprimés.")
    else:
        print("  La collection est déjà vide.")


async def main():
    """Point d'entrée principal."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Gestion des exemples de supervision pour l'agent supervisor"
    )
    parser.add_argument(
        "--init", 
        action="store_true",
        help="Initialiser/remplir la collection avec des exemples de base"
    )
    parser.add_argument(
        "--list", 
        action="store_true",
        help="Lister tous les exemples actuels"
    )
    parser.add_argument(
        "--clear", 
        action="store_true",
        help="Supprimer tous les exemples (DANGER)"
    )
    
    args = parser.parse_args()

    if args.clear:
        await clear_collection()
    elif args.list:
        await list_examples()
    else:
        # Par défaut: initialiser
        await init_collection()


if __name__ == "__main__":
    asyncio.run(main())
