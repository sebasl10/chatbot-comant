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


def merge_statistic_results(deps: ChatDeps) -> tuple[list[str], list[dict]]:
    """
    Fusionne le résultat de la requête principale et celui de la requête externe.

    ⚠️ Cette règle est la MÊME que celle que le back-end PHP doit appliquer quand il
    ré-exécute les deux requêtes persistées :

    1. la clé de jointure est l'ensemble des colonnes présentes dans LES DEUX résultats ;
    2. chaque ligne principale reçoit les colonnes supplémentaires du résultat externe ;
    3. une clé absente du résultat externe donne 0 (et non NULL) ;
    4. une clé présente uniquement côté externe (ex: un salarié absent toute la période,
       sans aucune saisie de temps) est ajoutée en fin de liste, ses colonnes principales
       valant 0.

    Renvoie ``(colonnes_fusionnées, lignes_fusionnées)``. Sans requête externe, renvoie
    le résultat principal inchangé.
    """
    main_rows = deps.last_result or []
    main_columns = list(deps.last_stats_columns)

    if not deps.external_columns:
        return main_columns, main_rows

    join_keys = [c for c in deps.external_columns if c in main_columns]
    external_values = [c for c in deps.external_columns if c not in main_columns]
    merged_columns = main_columns + external_values

    def _key(row: dict) -> tuple:
        return tuple(row.get(c) for c in join_keys)

    external_index = {_key(row): row for row in (deps.external_result or [])}

    merged_rows = []
    for row in main_rows:
        merged_row = dict(row)
        external_row = external_index.pop(_key(row), None) or {}
        for col in external_values:
            merged_row[col] = external_row.get(col) or 0
        merged_rows.append(merged_row)

    for external_row in external_index.values():
        merged_row = {
            col: external_row.get(col) if col in join_keys else 0 for col in main_columns
        }
        for col in external_values:
            merged_row[col] = external_row.get(col) or 0
        merged_rows.append(merged_row)

    return merged_columns, merged_rows


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
            Une DURÉE seule → "pie" (quel que soit le nombre de lignes) ; des valeurs
            numériques (comptages, moyennes) → "bar" ; une évolution temporelle → "line".
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

    if not ctx.deps.last_stats_sql:
        return {"ok": False, "error": "Aucune requête stats validée : appelle d'abord run_stats_sql."}

    # Les colonnes à décrire sont celles du résultat FUSIONNÉ (principal + externe).
    sql_columns, rows = merge_statistic_results(ctx.deps)
    join_keys = [c for c in ctx.deps.external_columns if c in ctx.deps.last_stats_columns]

    if graph_type not in GRAPH_TYPES:
        return {"ok": False, "error": f"graph_type invalide : {graph_type!r}. Valeurs autorisées : {list(GRAPH_TYPES)}."}

    if not description or not description.strip():
        return {"ok": False, "error": "description vide : reformule la demande de l'utilisateur en une phrase."}

    errors: list[str] = []
    keys = [c.get("key") for c in columns]

    if keys != sql_columns:
        errors.append(
            f"Les clés des colonnes doivent reprendre EXACTEMENT les colonnes du résultat "
            f"(requête principale puis colonnes ajoutées par la requête externe) : "
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

    # La clé de jointure sert de catégorie commune aux deux requêtes : c'est un `label`.
    for col in columns:
        if col["key"] in join_keys and col["role"] != "label":
            errors.append(
                f"Colonne {col['key']!r} : c'est la clé de jointure avec la requête externe, "
                f"son `role` doit être `label`."
            )

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
            # Le nombre de parts n'est PAS limité : la légende du camembert permet de filtrer.
            if len(value_cols) > 1:
                errors.append(
                    "Un camembert n'affiche qu'une seule série : utilise graph_type='table' "
                    f"pour {len(value_cols)} colonnes de valeurs."
                )
            if any(v < 0 for c in value_cols for v in [row.get(c["key"]) for row in rows] if v is not None):
                errors.append("Valeurs négatives : un camembert ne représente que des parts positives d'un total.")

        # Une durée n'a pas d'échelle lisible : un axe Y gradué en `h min s` est inexploitable.
        if graph_type == "bar" and all(c["format"] == "seconds" for c in value_cols):
            errors.append(
                "Toutes les colonnes de valeurs sont des durées : n'utilise pas graph_type='bar' "
                "(un axe Y en 'h min s' est illisible). Prends 'pie' s'il n'y a qu'une colonne de "
                "durée et que les valeurs sont positives — quel que soit le nombre de lignes — "
                "sinon 'table'."
            )

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

    # `last_result` est le résultat FUSIONNÉ : il doit décrire les mêmes colonnes que
    # `labels`, sinon le front recevrait un instantané incohérent avec ses métadonnées.
    merged_columns, merged_rows = merge_statistic_results(deps)

    # Filet de sécurité : une table sans métadonnées reste affichable par le front.
    graph_type = deps.graph_type or "table"
    labels = deps.labels or [
        {"key": key, "label": key, "role": "label" if i == 0 else "value", "format": "text" if i == 0 else "number"}
        for i, key in enumerate(merged_columns)
    ]

    statistic_id = await asyncio.to_thread(
        create_statistic,
        deps.user_id,
        deps.last_stats_sql,
        graph_type,
        deps.description,
        _json_dump(labels),
        deps.external_sql,
        _json_dump(merged_rows),
    )
    deps.events.statistic(statistic_id)
    return statistic_id
