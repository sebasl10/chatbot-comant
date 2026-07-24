#!/usr/bin/env python3
"""
Script de test rapide pour la recherche sémantique avec Chroma.

Définis ta query dans la fonction main() ci-dessous.
"""

import asyncio
import sys
sys.path.insert(0, '.')

from app.services.vectorstore import tickets_collection, TICKETS, get_embedding

async def main():
    # ── CONFIGURATION ────────────────────────────────────────────────────────
    query = "cinématique"  # ← MODIFIE TA QUERY ICI
    collection_name = TICKETS
    threshold= 0.55
    query_instruction = "Given a technical term or topic, retrieve customer support tickets that mention or relate to it, even briefly."
    query_embedding = await asyncio.to_thread(get_embedding, f"Instruct: {query_instruction}\nQuery: {query}")

    # ── EXÉCUTION ────────────────────────────────────────────────────────────
    collection = await tickets_collection()
    
    """ NEW_HNSW_CONFIG = {
        "hnsw": {
            "ef_search": 1000
        }
    }
    await collection.modify(configuration=NEW_HNSW_CONFIG) """
    print(collection.configuration_json)

    print(f"\n[RECHERCHE SÉMANTIQUE]")
    print(f"Collection: {collection_name}")
    print(f"Query: {query}")
    print(f"-" * 60)

    # Recherche sémantique
    results = await collection.query(
        query_embeddings=[query_embedding],
        n_results=3000,
        include=["documents", "metadatas", "distances"]
    )
    
    # Affichage des résultats
    if not results["documents"] or not results["documents"][0]:
        print("Aucun résultat trouvé.")
        return
    
    filtered_results = [
        (id, doc, meta, dist) 
        for id, doc, meta, dist in zip(
            results["ids"][0], results["documents"][0], results["metadatas"][0], results["distances"][0]
        )
        if dist < threshold
    ]
    
    for i, (id, doc, meta, dist) in enumerate(filtered_results):
        print(f"\n[{i+1}] Distance: {dist:.4f}")
        print(f"   ID: {id}")
        #print(f"   Contenu: {doc[:200]}..." if len(doc) > 200 else f"   Contenu: {doc}")


if __name__ == "__main__":
    asyncio.run(main())
