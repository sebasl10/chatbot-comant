from datetime import datetime, timedelta
from app.services.database import get_connection
from rapidfuzz import process, fuzz

SIMILARITY_THRESHOLD = 65
CACHEABLE_COLUMNS = {
    "branch_dev": ("project", "branch_dev"),
    "branch_travail": ("project", "branches"),
    "branch_release": ("project", "branch_release"),
    "client": ("client", "name"),
    "component": ("component", "name"),
    "product": ("product", "name"),
    "project": ("project", "code"),
    "tag": ("tag", "name"),
    "user": ("user", "username")
}

class EntityCache:
    def __init__(self, ttl_minutes: int = 30):
        self.ttl = timedelta(minutes=ttl_minutes)
        self._cache: dict[str, set[str]] = {}
        self._last_refresh: datetime | None = None

    def _needs_refresh(self) -> bool:
        if self._last_refresh is None:
            return True
        return datetime.now() - self._last_refresh > self.ttl

    def refresh(self):
        conn = get_connection()
        cursor = conn.cursor()
        for entity_type, (table, column) in CACHEABLE_COLUMNS.items():
            cursor.execute(f"SELECT DISTINCT `{column}` FROM `{table}` WHERE `{column}` IS NOT NULL")
            self._cache[entity_type] = {row[column] for row in cursor.fetchall()}
        cursor.close()
        conn.close()
        self._last_refresh = datetime.now()

    def get(self, entity_type: str) -> set[str]:
        if self._needs_refresh():
            self.refresh()
        return self._cache.get(entity_type, set())

entity_cache = EntityCache()

def link_entities(entities: list[dict]) -> dict:
    """
    Retourne pour chaque entité extraite :
    - "ok" si la valeur existe exactement
    - "suggestion" si un proche match est trouvé
    - "unknown" si aucun match satisfaisant
    """
    results = []

    for entity in entities:
        entity_type = entity["type"]
        value = entity["value"]
        valid_values = entity_cache.get(entity_type)

        if not valid_values:
            results.append({**entity, "status": "ok", "resolved": value})
            continue

        exact = next((v for v in valid_values if v.lower() == value.lower()), None)
        if exact:
            results.append({**entity, "status": "ok", "resolved": exact})
            continue

        match = process.extractOne(
            value.lower(),
            [v.lower() for v in valid_values],
            scorer=fuzz.WRatio,
            score_cutoff=SIMILARITY_THRESHOLD
        )

        if match:
            best_match_lower, score, _ = match
            best_match = next((v for v in valid_values if v.lower() == best_match_lower), None)
            results.append({
                **entity,
                "status": "suggestion",
                "resolved": None,
                "suggestion": best_match,
                "score": score
            })
        else:
            results.append({**entity, "status": "unknown", "resolved": None})

    return results

def get_unknown_entities_message(unknowns: list[dict]) -> str:
    """
    Génère un message pour les entités inconnues.
    """
    names = [f'<strong>{u["value"]}</strong> ({u["type"]})' for u in unknowns]
    return f"Je n'ai trouvé aucune correspondance exacte ou similaire pour : {', '.join(names)}. Vérifiez votre requête."

def get_suggestion_entities_message(suggestions: list[dict]) -> str:
    """
    Génère un message pour les entités avec des suggestions.
    """
    parts = []
    for s in suggestions:
        parts.append(
            f'<p>Le {s["type"]} <strong>{s["value"]}</strong> n\'existe pas. '
            f'Voulez-vous dire <strong>{s["suggestion"]}</strong>?</p>'
        )
    return "".join(parts)

async def handle_vocabulary_suggestions(entities_dict: dict) -> tuple[bool, str, dict | None]:
    """
    Traite les entités extraites et retourne :
    - un booléen indiquant si la requête doit être arrêtée (True si erreur de vocabulaire)
    - un message à afficher (si erreur)
    - un dictionnaire d'erreurs de vocabulaire (si suggestions)
    """
    linked = link_entities(entities_dict["entities"])
    suggestions = [e for e in linked if e["status"] == "suggestion"]
    unknowns = [e for e in linked if e["status"] == "unknown"]

    if unknowns:
        message = get_unknown_entities_message(unknowns)
        return True, message, None

    if suggestions:
        message = get_suggestion_entities_message(suggestions)
        return True, message, suggestions

    return False, "", None