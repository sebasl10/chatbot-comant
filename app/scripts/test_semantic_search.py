#!/usr/bin/env python3
"""
Script de test rapide pour la recherche sémantique avec Chroma.

Définis ta query dans la fonction main() ci-dessous.
"""

import sys
sys.path.insert(0, '.')

from app.services.vectorstore import tickets_collection, TICKETS, get_query_embedding

def main():
    # ── CONFIGURATION ────────────────────────────────────────────────────────
    query = "cinématique"  # ← MODIFIE TA QUERY ICI
    collection_name = TICKETS 
    n_results = 10
    threshold= 0.43
    query_instruction = (
        "Trouve les tickets pertinents pour une demande donnée en identifiant ceux qui mentionnent, décrivent ou traitent du sujet spécifié. "
        "Inclus les tickets qui contiennent des termes directement liés ou des concepts sémantiquement proches."
        "Donne la priorité aux tickets qui contiennent exactement le sujet."
        "Cherche les tickets qui parlent de: "
    )
    query_embedding = get_query_embedding(f"{query_instruction}{query}")
    
    # ── EXÉCUTION ────────────────────────────────────────────────────────────
    collection = tickets_collection()
    
    print(f"\n[RECHERCHE SÉMANTIQUE]")
    print(f"Collection: {collection_name}")
    print(f"Query: {query}")
    print(f"-" * 60)
    
    # Recherche sémantique
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=5000,
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
        print(f"   Contenu: {doc[:200]}..." if len(doc) > 200 else f"   Contenu: {doc}")


if __name__ == "__main__":
    main()
