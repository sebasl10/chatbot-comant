"""Contrôle de parité : recherche sémantique Chroma vs ancienne (MySQL/cosine).

Pour un jeu de requêtes, compare les ``ticket_id`` renvoyés par :
- l'ancien ``embedding.search`` (scan MySQL + cosine en Python), et
- le nouveau chemin Chroma (``get_embedding`` + ``vectorstore.query_tickets``).

Les deux utilisent les mêmes vecteurs et le même seuil : les ensembles doivent
être identiques. À lancer APRÈS la migration, avec MySQL + Ollama + .env.

    python -m app.scripts.check_chroma_parity
"""
from app.services.embedding import search, get_embedding
from app.services import vectorstore as vs

QUERIES = [
    "cinématique",
    "problème de connexion",
    "erreur d'affichage",
    "vitesse de rotation",
    "authentification",
]
THRESHOLD = 0.5


def main() -> None:
    all_ok = True
    for q in QUERIES:
        old_ids = {tid for tid, _ in search(q, THRESHOLD)}
        query_emb = get_embedding(q)[0]
        new_ids = set(vs.query_tickets(query_emb, THRESHOLD))

        only_old = old_ids - new_ids
        only_new = new_ids - old_ids
        status = "OK" if not only_old and not only_new else "DIFF"
        if status == "DIFF":
            all_ok = False
        print(f"[{status}] '{q}' : old={len(old_ids)} new={len(new_ids)}"
              + (f" | manquants dans Chroma={sorted(only_old)}" if only_old else "")
              + (f" | en trop dans Chroma={sorted(only_new)}" if only_new else ""))

    print("\n✅ Parité parfaite." if all_ok else "\n⚠️  Divergences détectées (voir ci-dessus).")


if __name__ == "__main__":
    main()
