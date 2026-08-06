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
import re
from decimal import Decimal

from pydantic_ai import RunContext

from app.agents.deps import ChatDeps
from app.services.database import (
    create_statistic,
    execute_select,
    get_statistic,
    update_statistic,
)

GRAPH_TYPES = ("pie", "bar", "line", "table")
ROLES = ("label", "value")
FORMATS = ("text", "date", "number", "seconds", "percent")

_DURATION_KEY = re.compile(r"second|seconde|duree|durée|duration", re.I)
_COUNT_KEY = re.compile(r"^(nb|nombre|count)_", re.I)


def _is_numeric(value) -> bool:
    return value is None or isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)


def _is_duration(col: dict) -> bool:
    """
    Colonne de durée : annoncée en `seconds`, ou dont l'alias SQL en est une
    (`temps_effectif_secondes`) même si l'agent s'est trompé de `format`.
    """
    key = col.get("key") or ""
    return not _COUNT_KEY.match(key) and (
        col.get("format") == "seconds" or bool(_DURATION_KEY.search(key))
    )


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
        merged_row = {col: external_row.get(col) if col in join_keys else 0 for col in main_columns}
        for col in external_values:
            merged_row[col] = external_row.get(col) or 0
        merged_rows.append(merged_row)

    return merged_columns, merged_rows


async def set_statistic_presentation(
    ctx: RunContext[ChatDeps],
    graph_type: str,
    description: str,
    columns: list[dict],
    user_requested_graph_type: bool = False,
) -> dict:
    """
    Décrit comment le front doit AFFICHER le résultat de la dernière requête stats.
    À appeler OBLIGATOIREMENT après un `run_stats_sql` réussi, et à chaque affinage de la
    présentation (type de graphe ou libellés) même sans nouvelle requête : cet appel
    REMPLACE entièrement la présentation précédente.

    En cas de description invalide, renvoie ``{"ok": False, "error": ...}`` SANS lever
    d'exception : corrige et rappelle ce tool.

    Args:
        graph_type: Type d'affichage : "pie", "bar", "line" ou "table" (si aucun graphe
            n'est adapté). Le front affiche TOUJOURS une table ; le graphe vient en plus.
            Une DURÉE seule → "pie" (quel que soit le nombre de lignes, et même si la
            requête est filtrée sur un seul salarié ou un seul projet) ; des valeurs
            numériques (comptages, moyennes) → "bar" ; une évolution temporelle → "line".
        description: Une phrase en français qui reformule la demande de l'utilisateur en
            gardant exactement les mêmes informations (indicateur, regroupement, filtres,
            période).
        columns: Un descripteur par colonne du résultat SQL, dans l'ordre d'affichage :
            - `key`    : nom EXACT de la colonne renvoyée par la requête (l'alias SQL)
            - `label`  : libellé lisible en français affiché à l'utilisateur : du TEXTE,
                         sans underscore, sans unité, jamais l'alias SQL recopié
                         (`temps_effectif_secondes` → "Temps effectif")
            - `role`   : "label" pour une colonne descriptive (catégorie / axe X),
                         "value" pour une colonne de valeurs numériques (série)
            - `format` : "text", "date", "number", "seconds" ou "percent". Toute DURÉE
                         (alias en `_secondes`, `SUM(duration)`, `time_estimate * 3600`)
                         → "seconds" : c'est ce format qui déclenche l'affichage en
                         `h min s`. "number" est réservé aux comptages et aux moyennes.
        user_requested_graph_type: `True` UNIQUEMENT si l'utilisateur a explicitement demandé
            ce type d'affichage (ex: "mets ça en barres"). Son choix lève alors les règles de
            LISIBILITÉ (une durée en barres), mais jamais les règles d'IMPOSSIBILITÉ
            (camembert à plusieurs séries ou à valeurs négatives), qui restent refusées.
    """
    print("[TOOL CALL] set_statistic_presentation")

    if not ctx.deps.last_stats_sql:
        return {
            "ok": False,
            "error": "Aucune requête stats validée : appelle d'abord run_stats_sql.",
        }

    # Les colonnes à décrire sont celles du résultat FUSIONNÉ (principal + externe).
    sql_columns, rows = merge_statistic_results(ctx.deps)
    join_keys = [c for c in ctx.deps.external_columns if c in ctx.deps.last_stats_columns]

    if graph_type not in GRAPH_TYPES:
        return {
            "ok": False,
            "error": f"graph_type invalide : {graph_type!r}. Valeurs autorisées : {list(GRAPH_TYPES)}.",
        }

    if not description or not description.strip():
        return {
            "ok": False,
            "error": "description vide : reformule la demande de l'utilisateur en une phrase.",
        }

    errors: list[str] = []
    keys = [c.get("key") for c in columns]

    if keys != sql_columns:
        errors.append(
            f"Les clés des colonnes doivent reprendre EXACTEMENT les colonnes du résultat "
            f"(requête principale puis colonnes ajoutées par la requête externe) : "
            f"attendu {sql_columns}, reçu {keys}."
        )

    for col in columns:
        key = str(col.get("key") or "")
        label = (col.get("label") or "").strip()
        if not label:
            errors.append(f"Colonne {key!r} : `label` manquant.")
        elif "_" in label or label == key:
            errors.append(
                f"Colonne {key!r} : `label` {label!r} reprend l'alias SQL. Le libellé est un "
                f"texte lisible en français, avec des espaces, sans underscore et sans unité "
                f"(ex: 'Temps effectif', 'Salarié', 'Nb de tickets')."
            )
        if col.get("role") not in ROLES:
            errors.append(f"Colonne {key!r} : `role` doit valoir {list(ROLES)}.")
        if col.get("format") not in FORMATS:
            errors.append(f"Colonne {key!r} : `format` doit valoir {list(FORMATS)}.")

    if errors:
        return {"ok": False, "error": " ".join(errors)}

    label_cols = [c for c in columns if c["role"] == "label"]
    value_cols = [c for c in columns if c["role"] == "value"]

    for col in value_cols:
        if _DURATION_KEY.search(col["key"]) and col["format"] != "seconds":
            errors.append(
                f"Colonne {col['key']!r} : c'est une DURÉE en secondes, son `format` doit être "
                f"`seconds` et non {col['format']!r} (sinon le front affiche un nombre brut de "
                f"secondes au lieu de 'h min s')."
            )
        elif _COUNT_KEY.match(col["key"]) and col["format"] == "seconds":
            errors.append(
                f"Colonne {col['key']!r} : c'est un COMPTAGE, son `format` doit être `number` "
                f"(avec `seconds` il serait affiché comme une durée)."
            )

    # La clé de jointure sert de catégorie commune aux deux requêtes : c'est un `label`.
    for col in columns:
        if col["key"] in join_keys and col["role"] != "label":
            errors.append(
                f"Colonne {col['key']!r} : c'est la clé de jointure avec la requête externe, "
                f"son `role` doit être `label`."
            )

    if not label_cols:
        errors.append(
            "Il faut au moins une colonne de rôle `label` (la catégorie décrite par la statistique)."
        )
    if not value_cols:
        errors.append("Il faut au moins une colonne de rôle `value` (l'indicateur chiffré).")

    # Une colonne `value` doit réellement contenir des nombres, sinon le graphe casse.
    for col in value_cols:
        if any(not _is_numeric(row.get(col["key"])) for row in rows):
            errors.append(
                f"Colonne {col['key']!r} : role `value` mais elle contient des valeurs non numériques."
            )

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
            if any(
                v < 0
                for c in value_cols
                for v in [row.get(c["key"]) for row in rows]
                if v is not None
            ):
                errors.append(
                    "Valeurs négatives : un camembert ne représente que des parts positives d'un total."
                )

        # Une durée n'a pas d'échelle lisible : un axe Y gradué en `h min s` est inexploitable.
        # Simple règle de lisibilité : un choix explicite de l'utilisateur la remplace.
        if (
            graph_type == "bar"
            and not user_requested_graph_type
            and all(_is_duration(c) for c in value_cols)
        ):
            errors.append(
                "Toutes les colonnes de valeurs sont des durées : n'utilise pas graph_type='bar' "
                "(un axe Y en 'h min s' est illisible). Prends 'pie' s'il n'y a qu'une colonne de "
                "durée et que les valeurs sont positives — quel que soit le nombre de lignes — "
                "sinon 'table'."
            )

    # Une répartition de temps (UNE durée par catégorie) se lit en camembert : la table
    # seule ne montre pas le poids de chaque part.
    elif (
        not user_requested_graph_type
        and len(label_cols) == 1
        and len(value_cols) == 1
        and _is_duration(value_cols[0])
        and label_cols[0]["format"] != "date"
        and len(rows) > 1
        and all((row.get(value_cols[0]["key"]) or 0) >= 0 for row in rows)
    ):
        errors.append(
            f"Cette statistique est une RÉPARTITION de durée : une seule catégorie "
            f"({label_cols[0]['key']!r}) et une seule colonne de durée "
            f"({value_cols[0]['key']!r}), toutes positives. Utilise graph_type='pie' "
            f"(la table reste affichée en plus) — le nombre de lignes n'y change rien."
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


def _json_load(value) -> list[dict] | None:
    """Relit une colonne JSON MySQL (le driver peut la renvoyer déjà décodée)."""
    if not value:
        return None
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def _fallback_column(key: str, index: int) -> dict:
    """
    Descripteur de secours quand l'agent n'a pas décrit la présentation : l'alias SQL
    devient un libellé lisible, et une durée garde son formatage `h min s`.
    """
    is_value = index > 0
    return {
        "key": key,
        "label": key.replace("_", " ").capitalize(),
        "role": "value" if is_value else "label",
        "format": ("seconds" if _DURATION_KEY.search(key) else "number") if is_value else "text",
    }


def _presentation(deps: ChatDeps) -> tuple[str, list[dict], list[dict]]:
    """
    Présentation à persister : le résultat FUSIONNÉ et les métadonnées qui le décrivent.

    Le résultat fusionné doit décrire les mêmes colonnes que `labels`, sinon le front
    recevrait un instantané incohérent avec ses métadonnées. Si l'agent n'a pas décrit
    la présentation, on retombe sur une table brute : elle reste affichable.
    """
    merged_columns, merged_rows = merge_statistic_results(deps)
    graph_type, labels = deps.graph_type, deps.labels

    if labels is None:
        # Affinage : `run_stats_sql` efface la présentation. Si l'agent a modifié la requête
        # sans la redécrire, on garde celle d'origine tant que les colonnes sont les mêmes.
        previous = deps.previous_statistic or {}
        previous_labels = previous.get("labels")
        if previous_labels and [c.get("key") for c in previous_labels] == merged_columns:
            labels = previous_labels
            graph_type = graph_type or previous.get("graph_type")

    graph_type = graph_type or "table"
    labels = labels or [_fallback_column(key, i) for i, key in enumerate(merged_columns)]
    return graph_type, labels, merged_rows


async def persist_statistic(deps: ChatDeps) -> int:
    """
    Crée une nouvelle ligne `statistics` avec la dernière requête SQL (statistiques) exécutée
    et la présentation décrite par l'agent.
    """
    if not deps.last_stats_sql:
        raise ValueError("Aucune requête SQL (stats) à persister (deps.last_stats_sql vide).")

    graph_type, labels, merged_rows = _presentation(deps)

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
    deps.events.statistic(statistic_id, sql=deps.last_stats_sql)
    return statistic_id


async def persist_statistic_affinage(deps: ChatDeps, statistic_id: int) -> int:
    """
    Met à jour la statistique existante (affinage)
    """
    if not deps.last_stats_sql:
        raise ValueError("Aucune requête SQL (stats) à persister (deps.last_stats_sql vide).")

    graph_type, labels, merged_rows = _presentation(deps)

    await asyncio.to_thread(
        update_statistic,
        statistic_id,
        deps.last_stats_sql,
        graph_type,
        deps.description,
        _json_dump(labels),
        deps.external_sql,
        _json_dump(merged_rows),
    )
    deps.events.statistic(statistic_id, sql=deps.last_stats_sql, intention="affinage_statistic")
    return statistic_id


def statistic_changed(deps: ChatDeps) -> bool:
    """
    L'agent a-t-il réellement modifié la statistique chargée ?

    Un tour d'affinage qui se termine par une demande de clarification (entité inconnue,
    graphe refusé) laisse la statistique intacte : ni mise à jour, ni rechargement du front.
    """
    previous = deps.previous_statistic
    if not previous:
        return True

    graph_type, labels, _ = _presentation(deps)
    return (
        deps.last_stats_sql != previous.get("sql")
        or deps.external_sql != previous.get("external_sql")
        or graph_type != previous.get("graph_type")
        or (deps.description or None) != (previous.get("description") or None)
        or labels != previous.get("labels")
    )


async def _run(sql: str, db: str) -> tuple[list[dict], list[str]]:
    """
    Ré-exécute une requête persistée
    """
    try:
        rows = await asyncio.to_thread(execute_select, sql, db)
    except Exception as e:
        print(f"[AFFINAGE STAT] Requête ({db}) injouable, résultat ignoré : {e}")
        return [], []
    return rows, list(rows[0].keys()) if rows else []


async def load_statistic(deps: ChatDeps, statistic_id: int) -> dict | None:
    """
    Charge dans les deps la statistique à affiner
    """
    row = await asyncio.to_thread(get_statistic, statistic_id)
    if not row or not row.get("sql_request"):
        return None

    deps.last_stats_sql = row["sql_request"]
    deps.external_sql = row.get("external_sql_request") or None
    deps.graph_type = row.get("graph_type")
    deps.description = row.get("description")
    deps.labels = _json_load(row.get("labels"))

    deps.last_result, deps.last_stats_columns = await _run(deps.last_stats_sql, "comant")
    if deps.external_sql:
        deps.external_result, deps.external_columns = await _run(deps.external_sql, "external")

    return {
        "sql": deps.last_stats_sql,
        "external_sql": deps.external_sql,
        "graph_type": deps.graph_type,
        "description": deps.description,
        "labels": deps.labels,
    }
