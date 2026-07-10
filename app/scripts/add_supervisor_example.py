"""Script pour ajouter un exemple manuellement à la collection supervisor_actions.

Usage :
    python -m app.scripts.add_supervisor_example --query "Ma requête" --action delegate_semantic_search

    python -m app.scripts.add_supervisor_example --query "Autre requête" --action delegate_new_research --description "Description optionnelle"

Actions disponibles :
- delegate_new_research : Recherche par filtres exacts (SQL)
- delegate_semantic_search : Recherche par thème/sujet
- delegate_conversation : Conversation (salutation, aide, hors-périmètre)
- delegate_correction : Enregistrement d'une correction/souvenir
- delegate_refine_search : Affinage d'une recherche existante
"""

import argparse
from app.services.vectorstore import add_supervisor_example, get_all_supervisor_examples
from app.config import settings


def add_example(query: str, action: str, description: str = ""):
    """Ajoute un nouvel exemple à la collection."""
    print("=" * 70)
    print("  Ajout d'un exemple de supervision")
    print("=" * 70)
    print(f"  URL Chroma: {settings.chroma_http_url}")
    print()
    
    print(f"  Requête: {query}")
    print(f"  Action: {action}")
    if description:
        print(f"  Description: {description}")
    print()
    
    # Vérifier que l'action est valide
    valid_actions = [
        "delegate_new_research",
        "delegate_semantic_search", 
        "delegate_conversation",
        "delegate_correction",
        "delegate_refine_search"
    ]
    
    if action not in valid_actions:
        print(f"  ❌ Action invalide. Actions autorisées: {', '.join(valid_actions)}")
        return
    
    # Vérifier si la requête existe déjà
    existing = get_all_supervisor_examples()
    for ex in existing:
        if ex["user_query"] == query:
            print(f"  ⚠️  Cette requête existe déjà avec l'action: {ex['metadata'].get('action', 'inconnu')}")
            response = input("  Voulez-vous l'ajouter quand même ? (y/n): ").strip().lower()
            if response != 'y':
                print("  ❌ Opération annulée.")
                return
            break
    
    # Ajouter l'exemple
    doc_id = add_supervisor_example(query, action, description)
    print(f"  ✅ Exemple ajouté avec succès!")
    print(f"  ID: {doc_id}")


def search_examples(query: str, n_results: int = 5):
    """Recherche des exemples similaires à une requête."""
    from app.services.vectorstore import get_supervisor_examples
    
    print("=" * 70)
    print(f"  Recherche d'exemples similaires à: '{query}'")
    print("=" * 70)
    
    results = get_supervisor_examples(query, n_results)
    
    if not results:
        print("  Aucun exemple trouvé.")
        return
    
    for i, result in enumerate(results, 1):
        action = result["metadata"].get("action", "inconnu")
        description = result["metadata"].get("description", "")
        distance = result.get("distance")
        
        print(f"\n  {i}. ID: {result['id']}")
        print(f"     Requête: {result['user_query']}")
        print(f"     Action: {action}")
        if description:
            print(f"     Description: {description}")
        if distance is not None:
            print(f"     Distance: {distance:.4f}")


def list_all_examples():
    """Liste tous les exemples."""
    from app.scripts.init_supervisor_actions import list_examples
    list_examples()


def main():
    """Point d'entrée principal."""
    parser = argparse.ArgumentParser(
        description="Ajouter et rechercher des exemples de supervision"
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Commande à exécuter')
    
    # Commande add
    add_parser = subparsers.add_parser('add', help='Ajouter un exemple')
    add_parser.add_argument(
        '--query', '-q',
        type=str,
        required=True,
        help='La requête utilisateur (ex: "Cherche les tickets PTC")'
    )
    add_parser.add_argument(
        '--action', '-a',
        type=str,
        required=True,
        help='Action à associer (ex: delegate_new_research)'
    )
    add_parser.add_argument(
        '--description', '-d',
        type=str,
        default="",
        help='Description optionnelle de l\'exemple'
    )
    
    # Commande search
    search_parser = subparsers.add_parser('search', help='Rechercher des exemples similaires')
    search_parser.add_argument(
        '--query', '-q',
        type=str,
        required=True,
        help='Requête pour la recherche'
    )
    search_parser.add_argument(
        '--n-results', '-n',
        type=int,
        default=5,
        help='Nombre de résultats (défaut: 5)'
    )
    
    # Commande list
    subparsers.add_parser('list', help='Lister tous les exemples')
    
    args = parser.parse_args()
    
    if args.command == 'add':
        add_example(args.query, args.action, args.description)
    elif args.command == 'search':
        search_examples(args.query, args.n_results)
    elif args.command == 'list':
        list_all_examples()
    else:
        # Si aucune commande n'est spécifiée, afficher l'aide
        parser.print_help()


if __name__ == "__main__":
    main()
