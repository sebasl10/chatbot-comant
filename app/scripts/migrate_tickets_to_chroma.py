"""Migration des embeddings de tickets : MySQL ``ticket_embedding`` → Chroma.

Réutilise les vecteurs DÉJÀ calculés (aucun ré-embedding). Joint la table
``ticket`` pour attacher des métadonnées filtrables (code, type, status, priority).

Usage (Ollama non requis, mais MySQL et un .env valides le sont) :

    python -m app.scripts.migrate_tickets_to_chroma

Idempotent : recrée la collection ``tickets`` à chaque exécution.
"""
import json

from app.services.database import get_connection
from app.services import vectorstore as vs

_BATCH = 1000


def _clean(value) -> str:
    return "" if value is None else str(value)


def main() -> None:
    # Repartir d'une collection propre.
    client = vs.get_client()
    try:
        client.delete_collection(vs.TICKETS)
        print(f"[reset] collection '{vs.TICKETS}' supprimée")
    except Exception:
        pass
    col = vs.tickets_collection()

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT te.ticket_id, te.embedding,
               t.code AS code, t.type AS type, t.status AS status, t.priority AS priority
        FROM ticket_embedding te
        JOIN ticket t ON t.id = te.ticket_id
        """
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    ids: list[str] = []
    embeddings: list[list[float]] = []
    metadatas: list[dict] = []
    documents: list[str] = []
    total = 0

    def flush():
        nonlocal ids, embeddings, metadatas, documents, total
        if not ids:
            return
        col.add(ids=ids, embeddings=embeddings, metadatas=metadatas, documents=documents)
        total += len(ids)
        print(f"  ... {total} tickets insérés")
        ids, embeddings, metadatas, documents = [], [], [], []

    for row in rows:
        # embedding stocké comme JSON [[...vecteur...]] -> on prend le vecteur interne.
        vec = json.loads(row["embedding"])[0]
        ids.append(str(row["ticket_id"]))
        embeddings.append(vec)
        metadatas.append(
            {
                "ticket_id": int(row["ticket_id"]),
                "code": _clean(row["code"]),
                "type": _clean(row["type"]),
                "status": _clean(row["status"]),
                "priority": _clean(row["priority"]),
            }
        )
        documents.append(_clean(row["code"]))
        if len(ids) >= _BATCH:
            flush()
    flush()

    print(f"\n✅ Migration terminée : {total} tickets dans la collection '{vs.TICKETS}'.")


if __name__ == "__main__":
    main()
