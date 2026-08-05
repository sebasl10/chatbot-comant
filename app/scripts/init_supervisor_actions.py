"""
Initialisation des exemples de routage de base pour l'agent superviseur.

Les exemples sont stockés dans la collection ``memories`` avec
``target_agent="supervisor"``, ``scope="global"`` et ``retrieval="contextual"`` :
le ``trigger`` (la requête type) est la clé embeddée, le ``content``
(« Délègue via … ») est le payload injecté. Ils sont
récupérés par similarité entre la nouvelle demande et les triggers, puis injectés
dans le system prompt du superviseur (``relevant_memories``), aux côtés des
corrections de routage écrites par l'agent memory.

Usage :
    python -m app.scripts.init_supervisor_actions --init   # ajoute les exemples de base
    python -m app.scripts.init_supervisor_actions list      # liste les exemples superviseur
    python -m app.scripts.init_supervisor_actions clear      # supprime les exemples superviseur
"""

import asyncio

from app.config import settings
from app.services import vectorstore as vs

# Exemples de base pour l'agent superviseur : (requête type, délégation attendue)
SUPERVISOR_EXAMPLES = [
    # Recherche exacte (SQL)
    {"user_query": "Cherche les tickets associés au client PTC", "action": "delegate_new_research"},
    {
        "user_query": "Trouve tous les tickets avec le statut 'En cours'",
        "action": "delegate_new_research",
    },
    {
        "user_query": "Liste les tickets de haute priorité créés cette semaine",
        "action": "delegate_new_research",
    },
    {"user_query": "Montre-moi les tickets assignés à dba", "action": "delegate_new_research"},
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
    # Recherche hybride (filtres exacts + thème)
    {
        "user_query": "Cherche les tickets du client TPC qui parlent d'annotations 3D",
        "action": "delegate_hybrid_search",
    },
    {
        "user_query": "Les tickets du projet Comant2026 qui parlent de cinématique",
        "action": "delegate_hybrid_search",
    },
    {
        "user_query": "Trouve les tickets assignés à sls concernant les performances",
        "action": "delegate_hybrid_search",
    },
    {
        "user_query": "Les bugs ouverts à propos de l'import de fichiers CAO",
        "action": "delegate_hybrid_search",
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
    {"user_query": "Bonjour, comment ça va ?", "action": "delegate_conversation"},
    {"user_query": "Merci pour ton aide", "action": "delegate_conversation"},
    {
        "user_query": "Peux-tu m'expliquer comment fonctionne ce système ?",
        "action": "delegate_conversation",
    },
    {"user_query": "Quelle est la météo aujourd'hui ?", "action": "delegate_conversation"},
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


async def _existing_supervisor_triggers() -> set[str]:
    # Les exemples de routage sont contextuels : le ``document`` est la requête
    # déclencheuse (le trigger). On dédoublonne dessus.
    col = await vs.memories_collection()
    res = await col.get(where={"target_agent": "supervisor"}, include=["documents"])
    return set(res.get("documents", []) or [])


async def init_examples():
    """Ajoute les exemples de base (idempotent : ignore les doublons).

    Chaque exemple est un souvenir **contextuel** : ``trigger`` = la requête type
    (clé de recherche embeddée), ``content`` = la délégation à appliquer (payload).
    """
    print("=" * 70)
    print("  Initialisation des exemples de routage du superviseur (memories)")
    print("=" * 70)
    print(f"  URL Chroma: {settings.chroma_http_url}\n")

    existing = await _existing_supervisor_triggers()
    added = 0
    for ex in SUPERVISOR_EXAMPLES:
        trigger = ex["user_query"]
        content = f"Délègue via {ex['action']}."
        if trigger in existing:
            print(f"  ⏭️  Déjà présent: {trigger} → {content}")
            continue
        await vs.add_memory(
            target_agent="supervisor",
            content=content,
            user_id=None,
            retrieval="contextual",
            trigger=trigger,
            scope="global",
        )
        print(f"  ✅ Ajouté: {trigger} → {content}")
        added += 1

    print(f"\n  ✅ {added} exemple(s) ajouté(s).")


async def list_examples():
    """Liste tous les souvenirs destinés au superviseur."""
    col = await vs.memories_collection()
    res = await col.get(where={"target_agent": "supervisor"}, include=["documents", "metadatas"])
    ids = res.get("ids", [])
    docs = res.get("documents", [])
    metas = res.get("metadatas", [])

    print("=" * 70)
    print(f"  Souvenirs superviseur ({len(ids)} au total)")
    print("=" * 70)
    if not ids:
        print("  Aucun souvenir trouvé.")
        return
    for i, (doc_id, doc, meta) in enumerate(zip(ids, docs, metas), 1):
        meta = meta or {}
        tag = f"{meta.get('retrieval', '?')}/{meta.get('scope', '?')}"
        if meta.get("retrieval") == "contextual":
            # doc = trigger (clé), meta["correction"] = payload injecté
            print(f"\n  {i}. [{tag}] trigger: {doc}")
            print(f"     → {meta.get('correction', '')}")
        else:
            print(f"\n  {i}. [{tag}] {doc}")
        print(f"     id={doc_id}")


async def clear_examples():
    """Supprime tous les souvenirs destinés au superviseur."""
    print("=" * 70)
    print("  ⚠️  Suppression de tous les souvenirs superviseur")
    print("=" * 70)
    response = input("  Êtes-vous sûr ? (y/n): ").strip().lower()
    if response != "y":
        print("  ❌ Opération annulée.")
        return
    col = await vs.memories_collection()
    res = await col.get(where={"target_agent": "supervisor"}, include=[])
    ids = res.get("ids", [])
    if ids:
        await col.delete(ids=ids)
        print(f"  ✅ {len(ids)} souvenir(s) supprimé(s).")
    else:
        print("  Aucun souvenir à supprimer.")


async def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Exemples de routage du superviseur (collection memories)"
    )
    parser.add_argument("--init", action="store_true", help="Ajouter les exemples de base")
    parser.add_argument("command", nargs="?", choices=["list", "clear"], help="list | clear")
    args = parser.parse_args()

    if args.init:
        await init_examples()
    elif args.command == "list":
        await list_examples()
    elif args.command == "clear":
        await clear_examples()
    else:
        parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())
