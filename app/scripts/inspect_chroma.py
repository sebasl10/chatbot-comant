"""Inspection des collections Chroma — affiche les premières lignes et statistiques.

Usage :
    python -m app.scripts.inspect_chroma
"""
import asyncio
from app.services import vectorstore as vs
from app.config import settings


def print_section(title: str):
    """Affiche un titre de section."""
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print("=" * 70)


def print_collection_header(name: str):
    """Affiche l'en-tête d'une collection."""
    print(f"\n{'─' * 50}")
    print(f"  Collection: {name}")
    print("─" * 50)


def format_value(value, max_length: int = 100) -> str:
    """Formate une valeur pour l'affichage (troncature si trop longue)."""
    s = str(value)
    if len(s) > max_length:
        return s[: max_length - 3] + "..."
    return s


async def get_first_rows(collection, limit: int = 5):
    """Récupère les premières lignes d'une collection."""
    try:
        # Récupérer les IDs
        res = await collection.get(limit=limit, include=["documents", "metadatas", "embeddings"])
        return {
            "ids": res.get("ids", []),
            "documents": res.get("documents", []),
            "metadatas": res.get("metadatas", []),
            "embeddings": res.get("embeddings", []),
        }
    except Exception as e:
        print(f"  ⚠️  Erreur lors de la récupération des données: {e}")
        return None


def print_first_rows(data: dict, limit: int = 5):
    """Affiche les premières lignes de manière formatée."""
    if not data or not data["ids"]:
        print("  Aucun document trouvé.")
        return

    ids = data["ids"]
    documents = data["documents"]
    metadatas = data["metadatas"]

    print(f"\n  📄 Premières {min(len(ids), limit)} lignes :")
    print()

    for i, (doc_id, doc, meta) in enumerate(zip(ids, documents, metadatas), 1):
        print(f"  {i}. ID: {doc_id}")
        print(f"     Document: {format_value(doc)}")
        if meta:
            print(f"     Métadonnées: {meta}")
        print()


async def print_statistics(collection):
    """Affiche les statistiques d'une collection."""
    try:
        count = await collection.count()
        print(f"\n  📊 Statistiques:")
        print(f"     • Nombre de documents: {count:,}")

        # Récupérer un échantillon pour les stats d'embeddings
        if count > 0:
            sample = await collection.get(limit=1, include=["embeddings"])
            if sample.get("embeddings"):
                embedding_dim = len(sample["embeddings"][0])
                print(f"     • Dimension des embeddings: {embedding_dim}")

        # Compter les métadonnées uniques (si applicable)
        if count > 0:
            all_metadata = await collection.get(include=["metadatas"])
            if all_metadata.get("metadatas"):
                all_metadatas = all_metadata["metadatas"]
                # Compter les catégories uniques (target_agent/kind ou type legacy)
                if all_metadatas and isinstance(all_metadatas[0], dict):
                    cat_key = None
                    for candidate in ("target_agent", "type"):
                        if any(candidate in (m or {}) for m in all_metadatas):
                            cat_key = candidate
                            break
                    if cat_key:
                        type_counts = {}
                        for meta in all_metadatas:
                            if cat_key in (meta or {}):
                                t = meta[cat_key]
                                type_counts[t] = type_counts.get(t, 0) + 1
                        print(f"     • Répartition par {cat_key}:")
                        for t, cnt in sorted(type_counts.items(), key=lambda x: -x[1]):
                            print(f"       - {t}: {cnt:,} ({cnt/count*100:.1f}%)")

                # Compter les user_id uniques (si applicable)
                if all_metadatas and isinstance(all_metadatas[0], dict):
                    user_ids = set()
                    for meta in all_metadatas:
                        if "user_id" in meta:
                            user_ids.add(meta["user_id"])
                    if user_ids:
                        print(f"     • Nombre d'utilisateurs uniques: {len(user_ids)}")

    except Exception as e:
        print(f"  ⚠️  Erreur lors du calcul des statistiques: {e}")


async def inspect_collection(name: str, collection_func):
    """Inspecte une collection spécifique."""
    print_collection_header(name)
    try:
        collection = await collection_func()

        # Statistiques
        await print_statistics(collection)

        # Premières lignes
        data = await get_first_rows(collection)
        if data:
            print_first_rows(data)
            
    except Exception as e:
        print(f"  ❌ Erreur: {e}")


async def main():
    """Point d'entrée principal."""
    print_section("Inspection des collections Chroma")
    print(f"URL du serveur: {settings.chroma_http_url}")

    # Liste des collections à inspecter
    collections = [
        (vs.TICKETS, vs.tickets_collection, "🎫"),
        (vs.MEMORIES, vs.memories_collection, "🧠"),
        (vs.CONVERSATION_SUMMARIES, vs.summaries_collection, "💬"),
    ]

    # Inspecter chaque collection
    for name, func, icon in collections:
        await inspect_collection(f"{icon} {name}", func)

    # Résumé global
    print_section("Résumé global")
    try:
        client = await vs.get_client()
        all_collections = await client.list_collections()
        print(f"\n  Nombre total de collections: {len(all_collections)}")
        for col in all_collections:
            print(f"    - {col.name}: {await col.count()} documents")
    except Exception as e:
        print(f"  ⚠️  Impossible de lister toutes les collections: {e}")

    print(f"\n✅ Inspection terminée.")


if __name__ == "__main__":
    asyncio.run(main())
