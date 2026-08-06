import json
import re
from datetime import datetime, timedelta

from rapidfuzz import fuzz, process

from app.services.database import get_connection

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
    "user": ("user", "username"),
}

_MONTHS = (
    "janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[uû]t|septembre|octobre|novembre|d[ée]cembre"
)
_UNAMBIGUOUS_MONTHS = _MONTHS.replace("|mai|", "|")
_PERIOD_PATTERNS = (
    r"(19|20|21)\d{2}",  # une année seule : 2026
    r"\d{4}-\d{2}(-\d{2})?",  # 2026-03, 2026-03-15
    r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}",  # 15/03/2026
    rf"{_UNAMBIGUOUS_MONTHS}",  # mars
    rf"(en|le|d[ée]but|fin|courant)\s+({_MONTHS})(\s+(19|20|21)\d{{2}})?",  # en mai 2026
    rf"({_MONTHS})\s+(19|20|21)\d{{2}}",  # mai 2026
    # ce mois-ci, cette année, le mois dernier, l'année passée
    r"(ce|cet|cette|le|la|l')\s*(mois|semaine|ann[ée]e|jour|trimestre|semestre)"
    r"([-\s](ci|derni[eè]re?|pass[ée]e?|prochaine?|en\s+cours))?",
    r"(hier|aujourd'hui|demain)",
    r"(les\s+)?\d+\s*(derni[eè]rs?\s+)?(jours?|semaines?|mois|ans?|ann[ée]es?)",  # 30 derniers jours
)
_PERIOD = re.compile(rf"^\s*(?:{'|'.join(_PERIOD_PATTERNS)})\s*$", re.I)


def is_period(value: str) -> bool:
    """Une date, une année ou une période relative — jamais une entité du vocabulaire."""
    return bool(_PERIOD.match(value or ""))


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
            cursor.execute(
                f"SELECT DISTINCT `{column}` FROM `{table}` WHERE `{column}` IS NOT NULL"
            )
            rows = cursor.fetchall()
            # Cas spécial pour branch_travail (branches séparées par des virgules)
            if entity_type == "branch_travail":
                values = set()
                for row in rows:
                    branches_str = row[column]
                    if branches_str:
                        branches_list = [branch.strip() for branch in branches_str.split(",")]
                        values.update(branches_list)
                self._cache[entity_type] = values
            else:
                self._cache[entity_type] = []
                for row in rows:
                    self._cache[entity_type].append(row[column])
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
    - "ignored" si la valeur est une période (date, année) et non du vocabulaire métier
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

        if is_period(value):
            results.append(
                {
                    **entity,
                    "status": "ignored",
                    "resolved": None,
                    "reason": (
                        f"{value!r} est une période (date, année, mois), pas une entité du "
                        f"vocabulaire métier. Ne demande AUCUNE clarification à l'utilisateur "
                        f"à son sujet : traduis-la directement en filtre de date dans le SQL "
                        f"(ex: YEAR(<colonne_date>) = 2026)."
                    ),
                }
            )
            continue

        match = process.extractOne(
            value.lower(),
            [v.lower() for v in valid_values],
            scorer=fuzz.WRatio,
            score_cutoff=SIMILARITY_THRESHOLD,
        )

        if match:
            best_match_lower, score, _ = match
            best_match = next((v for v in valid_values if v.lower() == best_match_lower), None)
            results.append(
                {
                    **entity,
                    "status": "suggestion",
                    "resolved": None,
                    "suggestion": best_match,
                    "score": score,
                }
            )
        else:
            results.append({**entity, "status": "unknown", "resolved": None})

    return results


def get_unknown_entities_message(unknowns: list[dict]) -> str:
    """
    Génère un message pour les entités inconnues.
    """
    names = [f"<strong>{u['value']}</strong> ({u['type']})" for u in unknowns]
    return f"Je n'ai trouvé aucune correspondance exacte ou similaire pour : {', '.join(names)}. Vérifiez votre requête."


def get_suggestion_entities_message(suggestions: list[dict]) -> str:
    """
    Génère un message pour les entités avec des suggestions.
    """
    type_to_article_and_name = {
        "branch_dev": ("La", "branche de développement"),
        "branch_travail": ("La", "branche de travail"),
        "branch_release": ("La", "branche de release"),
        "client": ("Le", "client"),
        "component": ("Le", "composant"),
        "product": ("Le", "produit"),
        "project": ("Le", "projet"),
        "tag": ("Le", "tag"),
        "user": ("L'", "utilisateur"),
    }
    parts = []
    for s in suggestions:
        type_ = s["type"]
        article, name_fr = type_to_article_and_name.get(type_, ("Le", type_))
        parts.append(
            f"<p>{article} {name_fr} <strong>{s['value']}</strong> n'existe pas. "
            f"Voulez-vous dire <strong>{s['suggestion']}</strong>?</p>"
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
    print(
        f"\n{'─' * 60}\n[ENTITY LINKING RESULT]\n{json.dumps(linked, indent=2, ensure_ascii=False)}\n{'─' * 60}"
    )
    suggestions = [e for e in linked if e["status"] == "suggestion"]
    unknowns = [e for e in linked if e["status"] == "unknown"]

    if unknowns:
        message = get_unknown_entities_message(unknowns)
        return True, message, None

    if suggestions:
        message = get_suggestion_entities_message(suggestions)
        return True, message, suggestions

    return False, "", None
