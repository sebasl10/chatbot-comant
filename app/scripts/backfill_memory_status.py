"""Backfill du champ metadata ``status`` sur les souvenirs existants.

Prérequis à la réconciliation à l'écriture (couche 1) : ``get_memories_text``
et ``find_similar_contextual_memories`` filtrent désormais sur
``status != "superseded"``. Les souvenirs créés avant l'introduction de ce
champ n'ont pas de ``status`` du tout : ce script leur assigne "active" pour
qu'ils restent visibles.

Idempotent (ne touche pas les documents qui ont déjà un ``status``).
À lancer une fois, à la main, stack (Chroma) démarrée :

    python -m app.scripts.backfill_memory_status          # dry-run (défaut)
    python -m app.scripts.backfill_memory_status --apply   # applique réellement
"""
import asyncio
import sys
from app.services import vectorstore as vs


async def main():
    apply = "--apply" in sys.argv
    col = await vs.memories_collection()

    res = await col.get(include=["metadatas"])
    ids = res.get("ids", [])
    metas = res.get("metadatas", [])

    to_fix = [
        (doc_id, meta) for doc_id, meta in zip(ids, metas)
        if not isinstance(meta, dict) or "status" not in meta
    ]

    print(f"Total souvenirs : {len(ids)}")
    print(f"Sans 'status'   : {len(to_fix)}")

    if not to_fix:
        print("Rien à faire.")
        return

    if not apply:
        print("\nDRY-RUN — aucun souvenir modifié. Relancer avec --apply pour appliquer.")
        for doc_id, meta in to_fix[:10]:
            print(f"  - {doc_id} : {meta}")
        if len(to_fix) > 10:
            print(f"  ... et {len(to_fix) - 10} de plus.")
        return

    for doc_id, meta in to_fix:
        new_meta = {**(meta or {}), "status": "active"}
        await col.update(ids=[doc_id], metadatas=[new_meta])
    print(f"\n{len(to_fix)} souvenir(s) mis à jour avec status='active'.")


if __name__ == "__main__":
    asyncio.run(main())
