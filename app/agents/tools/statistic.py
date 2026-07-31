"""
Présentation et persistance des statistiques.

L'agent statistiques ne produit pas seulement une requête SQL : il décrit aussi
COMMENT afficher le résultat (type de graphe, libellés, rôle et format de chaque
colonne). Cette description est validée contre le résultat réel de la requête,
puis persistée.
"""

import asyncio
import datetime
import json
from decimal import Decimal

from pydantic_ai import RunContext

from app.agents.deps import ChatDeps
from app.services.database import create_statistic

GRAPH_TYPES = ("pie", "bar", "line", "table")
ROLES = ("label", "value")
FORMATS = ("text", "date", "number", "seconds", "percent")


def _is_numeric(value) -> bool:
    return value is None or isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)


async def set_statistic_presentation(
    ctx: RunContext[ChatDeps],
    graph_type: str,
    description: str,
    columns: list[dict],
) -> dict:
    """
    Décrit comment le front doit AFFICHER le résultat de la dernière requête stats.
    À appeler OBLIGATOIREMENT après un `run_stats_sql` réussi.

    En cas de description invalide, renvoie ``{"ok": False, "error": ...}`` SANS lever
    d'exception : corrige et rappelle ce tool.

    Args:
        graph_type: Type d'affichage : "pie", "bar", "line" ou "table" (si aucun graphe
            n'est adapté). Le front affiche TOUJOURS une table ; le graphe vient en plus.
        description: Une phrase en français qui reformule la demande de l'utilisateur en
            gardant exactement les mêmes informations (indicateur, regroupement, filtres,
            période).
        columns: Un descripteur par colonne du résultat SQL, dans l'ordre d'affichage :
            - `key`    : nom EXACT de la colonne renvoyée par la requête (l'alias SQL)
            - `label`  : libellé lisible en français affiché à l'utilisateur
            - `role`   : "label" pour une colonne descriptive (catégorie / axe X),
                         "value" pour une colonne de valeurs numériques (série)
            - `format` : "text", "date", "number", "seconds" (durée, affichée en h min s
              par le front) ou "percent"
    """
    print("[TOOL CALL] set_statistic_presentation")

    sql_columns = ctx.deps.last_stats_columns
    if not ctx.deps.last_stats_sql:
        return {"ok": False, "error": "Aucune requête stats validée : appelle d'abord run_stats_sql."}

    if graph_type not in GRAPH_TYPES:
        return {"ok": False, "error": f"graph_type invalide : {graph_type!r}. Valeurs autorisées : {list(GRAPH_TYPES)}."}

    if not description or not description.strip():
        return {"ok": False, "error": "description vide : reformule la demande de l'utilisateur en une phrase."}

    errors: list[str] = []
    keys = [c.get("key") for c in columns]

    if keys != sql_columns:
        errors.append(
            f"Les clés des colonnes doivent reprendre EXACTEMENT les colonnes du résultat SQL : "
            f"attendu {sql_columns}, reçu {keys}."
        )

    for col in columns:
        if not col.get("label"):
            errors.append(f"Colonne {col.get('key')!r} : `label` manquant.")
        if col.get("role") not in ROLES:
            errors.append(f"Colonne {col.get('key')!r} : `role` doit valoir {list(ROLES)}.")
        if col.get("format") not in FORMATS:
            errors.append(f"Colonne {col.get('key')!r} : `format` doit valoir {list(FORMATS)}.")

    if errors:
        return {"ok": False, "error": " ".join(errors)}

    label_cols = [c for c in columns if c["role"] == "label"]
    value_cols = [c for c in columns if c["role"] == "value"]
    rows = ctx.deps.last_result or []

    if not label_cols:
        errors.append("Il faut au moins une colonne de rôle `label` (la catégorie décrite par la statistique).")
    if not value_cols:
        errors.append("Il faut au moins une colonne de rôle `value` (l'indicateur chiffré).")

    # Une colonne `value` doit réellement contenir des nombres, sinon le graphe casse.
    for col in value_cols:
        if any(not _is_numeric(row.get(col["key"])) for row in rows):
            errors.append(f"Colonne {col['key']!r} : role `value` mais elle contient des valeurs non numériques.")

    if graph_type != "table":
        if len(label_cols) > 1:
            errors.append(
                f"graph_type={graph_type!r} impose UNE seule colonne `label` (l'axe des catégories) ; "
                f"{len(label_cols)} reçues. Une statistique croisant deux dimensions doit utiliser "
                f"graph_type='table'."
            )
        if graph_type == "pie":
            if len(value_cols) > 1:
                errors.append(
                    "Un camembert n'affiche qu'une seule série : utilise graph_type='bar' "
                    f"(ou 'table') pour {len(value_cols)} colonnes de valeurs."
                )
            if any(v < 0 for c in value_cols for v in [row.get(c["key"]) for row in rows] if v is not None):
                errors.append("Valeurs négatives : un camembert ne représente que des parts positives d'un total.")

    if errors:
        return {"ok": False, "error": " ".join(errors)}

    ctx.deps.graph_type = graph_type
    ctx.deps.description = description.strip()
    ctx.deps.labels = columns
    return {"ok": True, "graph_type": graph_type}


def _json_dump(value) -> str | None:
    """Sérialise pour une colonne JSON MySQL (Decimal / dates ne le sont pas nativement)."""
    if value is None:
        return None

    def default(obj):
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, (datetime.datetime, datetime.date, datetime.time)):
            return obj.isoformat()
        return str(obj)

    return json.dumps(value, default=default, ensure_ascii=False)


async def persist_statistic(deps: ChatDeps) -> int:
    """
    Crée une nouvelle ligne `statistics` avec la dernière requête SQL (statistiques) exécutée
    et la présentation décrite par l'agent.
    """
    if not deps.last_stats_sql:
        raise ValueError("Aucune requête SQL (stats) à persister (deps.last_stats_sql vide).")

    # Filet de sécurité : une table sans métadonnées reste affichable par le front.
    graph_type = deps.graph_type or "table"
    labels = deps.labels or [
        {"key": key, "label": key, "role": "label" if i == 0 else "value", "format": "text" if i == 0 else "number"}
        for i, key in enumerate(deps.last_stats_columns)
    ]

    statistic_id = await asyncio.to_thread(
        create_statistic,
        deps.user_id,
        deps.last_stats_sql,
        graph_type,
        deps.description,
        _json_dump(labels),
        deps.external_sql,
        _json_dump(deps.last_result),
    )
    deps.events.statistic(statistic_id)
    return statistic_id
