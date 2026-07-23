"""
Ajout / recherche manuels d'exemples de routage pour l'agent superviseur.

Les exemples vivent dans la collection ``memories`` (``target_agent="supervisor"``,
``kind="routing"``, ``polarity="positive"``, ``scope="global"``), au même endroit
que les corrections de routage écrites par l'agent memory.

Usage :
    Ajouter : python -m app.scripts.add_supervisor_example add --query "Ma requête" --action delegate_semantic_search
    Chercher: python -m app.scripts.add_supervisor_example search --query "tickets embeddings"
    Lister  : python -m app.scripts.add_supervisor_example list

Actions disponibles :
- delegate_new_research   : Recherche par filtres exacts (SQL)
- delegate_semantic_search: Recherche par thème/sujet
- delegate_conversation   : Conversation (salutation, aide, hors-périmètre)
- delegate_correction     : Enregistrement d'une correction/souvenir
- delegate_refine_search  : Affinage d'une recherche existante
"""

import argparse
import asyncio
from app.services import vectorstore as vs
from app.config import settings

VALID_ACTIONS = [
    "delegate_new_research",
    "delegate_semantic_search",
    "delegate_conversation",
    "delegate_correction",
    "delegate_refine_search",
]


async def add_example(query: str, action: str):
    """Ajoute un exemple de routage global (positif) pour le superviseur."""
    print("=" * 70)
    print("  Ajout d'un exemple de routage superviseur")
    print("=" * 70)
    print(f"  URL Chroma: {settings.chroma_http_url}\n")

    if action not in VALID_ACTIONS:
        print(f"  ❌ Action invalide. Actions autorisées: {', '.join(VALID_ACTIONS)}")
        return

    content = f"Pour une demande comme « {query} », délègue via {action}."
    doc_id = await vs.add_memory(
        target_agent="supervisor",
        kind="routing",
        content=content,
        user_id=None,
        polarity="positive",
        scope="global",
    )
    print(f"  ✅ Ajouté: {content}")
    print(f"  ID: {doc_id}")


async def search_examples(query: str, n_results: int = 5):
    """Recherche sémantique parmi les souvenirs du superviseur."""
    print("=" * 70)
    print(f"  Recherche d'exemples similaires à: '{query}'")
    print("=" * 70)

    text = await vs.get_memories_text("supervisor", user_id=None, query=query, k=n_results)
    print(text or "  Aucun exemple trouvé.")


async def main():
    parser = argparse.ArgumentParser(description="Gérer les exemples de routage du superviseur")
    subparsers = parser.add_subparsers(dest="command", help="Commande à exécuter")

    add_parser = subparsers.add_parser("add", help="Ajouter un exemple")
    add_parser.add_argument("--query", "-q", type=str, required=True, help="La requête utilisateur type")
    add_parser.add_argument("--action", "-a", type=str, required=True, help="Délégation à associer (ex: delegate_new_research)")

    search_parser = subparsers.add_parser("search", help="Rechercher des exemples similaires")
    search_parser.add_argument("--query", "-q", type=str, required=True, help="Requête pour la recherche")
    search_parser.add_argument("--n-results", "-n", type=int, default=5, help="Nombre de résultats (défaut: 5)")

    subparsers.add_parser("list", help="Lister tous les souvenirs superviseur")

    args = parser.parse_args()

    if args.command == "add":
        await add_example(args.query, args.action)
    elif args.command == "search":
        await search_examples(args.query, args.n_results)
    elif args.command == "list":
        from app.scripts.init_supervisor_actions import list_examples
        await list_examples()
    else:
        parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())
