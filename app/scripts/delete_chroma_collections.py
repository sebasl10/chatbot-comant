"""Suppression des collections Chroma.

Usage :
    python -m app.scripts.delete_chroma_collections

Modifiez la liste COLLECTIONS_TO_DELETE pour definir les collections a supprimer.
"""

import asyncio

from app.config import settings
from app.services import vectorstore as vs

# Liste des collections a supprimer - MODIFIEZ CI-DESSOUS
COLLECTIONS_TO_DELETE = ["supervisor_actions", "memories"]


async def main():
    """Supprime les collections specifiees dans COLLECTIONS_TO_DELETE."""
    print(f"Suppression des collections Chroma - Serveur: {settings.chroma_http_url}")
    print("-" * 70)

    client = await vs.get_client()

    print(f"Collections a supprimer: {len(COLLECTIONS_TO_DELETE)}")
    for col_name in COLLECTIONS_TO_DELETE:
        print(f"  - {col_name}")
    print()

    results = {}
    for col_name in COLLECTIONS_TO_DELETE:
        try:
            collection = await client.get_collection(col_name)
            count = await collection.count()
            await client.delete_collection(col_name)
            results[col_name] = True
            print(f"Supprimée: {col_name} ({count} documents)")
        except Exception as e:
            results[col_name] = False
            print(f"Erreur {col_name}: {e}")

    print("-" * 70)
    success = sum(1 for r in results.values() if r)
    print(f"Resultat: {success}/{len(results)} collections supprimées")


if __name__ == "__main__":
    asyncio.run(main())
