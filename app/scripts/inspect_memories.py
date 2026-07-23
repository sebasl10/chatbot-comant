"""Inspection des mémoires Chroma — affiche toutes les entrées groupées par type.

Usage :
    python -m app.scripts.inspect_memories
"""
import asyncio
from app.services import vectorstore as vs
from app.config import settings


def print_section(title: str):
    """Affiche un titre de section."""
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print("=" * 70)


def print_type_header(type_name: str, count: int):
    """Affiche l'en-tête d'un type de mémoire."""
    print(f"\n{'─' * 50}")
    print(f"  Type: {type_name} ({count} entrées)")
    print("─" * 50)


def format_value(value, max_length: int = 150) -> str:
    """Formate une valeur pour l'affichage (troncature si trop longue)."""
    s = str(value)
    if len(s) > max_length:
        return s[: max_length - 3] + "..."
    return s


async def get_all_memories(collection, batch_size: int = 100):
    """Récupère toutes les mémoires de la collection par batches."""
    try:
        # Récupérer le count
        count_raw = await collection.count()
        count = int(count_raw) if hasattr(count_raw, '__len__') else int(count_raw)

        all_data = {
            "ids": [],
            "documents": [],
            "metadatas": [],
        }

        # Récupérer par batches pour éviter les problèmes de mémoire
        offset = 0
        while offset < count:
            batch = await collection.get(
                limit=min(batch_size, count - offset),
                offset=offset,
                include=["documents", "metadatas"]
            )
            all_data["ids"].extend(batch.get("ids", []))
            all_data["documents"].extend(batch.get("documents", []))
            all_data["metadatas"].extend(batch.get("metadatas", []))
            offset += batch_size
        
        return all_data
    except Exception as e:
        print(f"  ⚠️  Erreur lors de la récupération des mémoires: {e}")
        return None


def print_memories_by_type(data: dict):
    """Affiche les mémoires groupées par type."""
    if not data or len(data.get("ids", [])) == 0:
        print("  Aucun document trouvé.")
        return

    # Regrouper par target_agent / kind
    memories_by_type = {}
    for doc_id, doc, meta in zip(data["ids"], data["documents"], data["metadatas"]):
        # Grouper par "target_agent/kind" des métadonnées
        if meta and isinstance(meta, dict):
            mem_type = f"{meta.get('target_agent', '?')}/{meta.get('kind', '?')}"
        else:
            mem_type = "unknown"

        if mem_type not in memories_by_type:
            memories_by_type[mem_type] = []

        memories_by_type[mem_type].append({
            "id": doc_id,
            "document": doc,
            "metadata": meta
        })
    
    # Afficher chaque type
    for mem_type, memories in memories_by_type.items():
        print_type_header(mem_type, len(memories))
        
        for i, mem in enumerate(memories, 1):
            print(f"\n  {i}. {mem['document']}")
            if mem["metadata"]:
                meta_str = ", ".join([f"{key}:{value}" for key, value in mem["metadata"].items()])
                print(f"     {meta_str}")
            print()


async def main():
    """Point d'entrée principal."""
    print_section("Inspection des mémoires Chroma")
    print(f"URL du serveur: {settings.chroma_http_url}")

    try:
        collection = await vs.memories_collection()

        # Récupérer toutes les mémoires
        print_section(f"Collection: memories (🧠)")
        data = await get_all_memories(collection)

        if data:
            # Afficher le nombre total
            count = len(data.get("ids", []))
            print(f"\n  📊 Total: {count:,} mémoires")
            
            # Afficher groupées par type
            print_memories_by_type(data)
        
    except Exception as e:
        print(f"  ❌ Erreur: {e}")
    
    print(f"\n✅ Inspection terminée.")


if __name__ == "__main__":
    asyncio.run(main())