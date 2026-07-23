"""Suppression de toutes les collections Chroma.

Usage :
    python -m app.scripts.delete_chroma_collections
"""
import asyncio
from app.services import vectorstore as vs
from app.config import settings


async def main():
    """Supprime toutes les collections Chroma et affiche les resultats."""
    print(f"Suppression des collections Chroma - Serveur: {settings.chroma_http_url}")
    print("-" * 70)

    client = await vs.get_client()
    collections = await client.list_collections()

    if not collections:
        print("Aucune collection trouvée.")
        return

    print(f"Collections a supprimer: {len(collections)}")
    for col in collections:
        count = await col.count()
        print(f"  - {col.name}: {count} documents")
    print()

    results = {}
    for col in collections:
        try:
            await client.delete_collection(col.name)
            results[col.name] = True
            print(f"Supprimée: {col.name}")
        except Exception as e:
            results[col.name] = False
            print(f"Erreur {col.name}: {e}")

    print("-" * 70)
    success = sum(1 for r in results.values() if r)
    print(f"Resultat: {success}/{len(results)} collections supprimées")


if __name__ == "__main__":
    asyncio.run(main())
