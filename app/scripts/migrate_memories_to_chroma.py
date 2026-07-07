"""Migration des souvenirs : fichiers Markdown ``app/memory/**`` → Chroma.

Chaque fichier ``{type}.md`` contient des entrées au format écrit par l'ancien
``save_memory_to_md`` :

    ## 2024-01-02 10:00:00

    [Utilisateur: alice] contenu du souvenir

    ---

Le dossier ``_global`` héberge ``expand_vocabulary`` (souvenirs partagés) ; les
autres dossiers portent le nom d'utilisateur.

Usage (MySQL + Ollama + .env requis — Ollama embarque les souvenirs) :

    python -m app.scripts.migrate_memories_to_chroma

Idempotent : recrée la collection ``memories`` à chaque exécution.
"""
import glob
import os

from app.services.database import get_connection
from app.services import vectorstore as vs

MEMORY_ROOT = os.path.join("app", "memory")
GLOBAL_DIR = "_global"


def parse_memory_file(text: str) -> list[tuple[str | None, str]]:
    """Parse le contenu d'un .md -> liste de (username|None, contenu).

    Fonction pure (testable hors-ligne). ``username`` = None si le préfixe
    ``[Utilisateur: X]`` est absent.
    """
    entries: list[tuple[str | None, str]] = []
    for block in text.split("---"):
        lines = [ln for ln in block.strip().splitlines() if ln.strip()]
        # Retirer l'en-tête de date "## ..."
        lines = [ln for ln in lines if not ln.strip().startswith("## ")]
        content = " ".join(lines).strip()
        if not content:
            continue
        username = None
        if content.startswith("[Utilisateur:"):
            end = content.find("]")
            if end != -1:
                username = content[len("[Utilisateur:"):end].strip()
                content = content[end + 1:].strip()
        entries.append((username, content))
    return entries


def _user_id_for(username: str, cache: dict) -> int:
    if username in cache:
        return cache[username]
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM user WHERE username = %s", (username,))
            row = cursor.fetchone()
            uid = int(row["id"]) if row else -1
    finally:
        conn.close()
    cache[username] = uid
    return uid


def main() -> None:
    client = vs.get_client()
    try:
        client.delete_collection(vs.MEMORIES)
        print(f"[reset] collection '{vs.MEMORIES}' supprimée")
    except Exception:
        pass
    vs.memories_collection()

    uid_cache: dict[str, int] = {}
    total = 0

    for path in glob.glob(os.path.join(MEMORY_ROOT, "**", "*.md"), recursive=True):
        mem_type = os.path.splitext(os.path.basename(path))[0]
        parent = os.path.basename(os.path.dirname(path))
        is_global = parent == GLOBAL_DIR
        with open(path, "r", encoding="utf-8") as f:
            entries = parse_memory_file(f.read())

        for username, content in entries:
            uname = username or (None if is_global else parent)
            if is_global:
                user_id = -1
            elif uname:
                user_id = _user_id_for(uname, uid_cache)
            else:
                user_id = -1
            vs.add_memory(mem_type, content, user_id=user_id, username=uname or "")
            total += 1
        print(f"  {path} -> {len(entries)} souvenirs")

    print(f"\n✅ Migration terminée : {total} souvenirs dans la collection '{vs.MEMORIES}'.")


if __name__ == "__main__":
    main()
