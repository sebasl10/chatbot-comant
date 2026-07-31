"""
Tools base de données : schéma + exécution SQL avec boucle d'auto-correction.

Ces fonctions sont enregistrées comme tools Pydantic AI sur les agents SQL.
Les appels bloquants (pymysql) sont déportés sur un thread pour ne pas figer
la boucle asyncio pendant le streaming.
"""

import asyncio

from pydantic_ai import RunContext

from app.agents.deps import ChatDeps
from app.services.database import execute_select, get_db_schema

_MAX_SAMPLE = 5


async def db_schema(ctx: RunContext[ChatDeps]) -> str:
    """
    Retourne le schéma de la base (tables, colonnes, types, clés étrangères)
    au format JSON. À appeler avant d'écrire une requête SQL.
    """
    return await asyncio.to_thread(get_db_schema)


async def run_sql(ctx: RunContext[ChatDeps], sql: str) -> dict:
    """
    Exécute une requête SELECT et renvoie le nombre de résultats

    IMPORTANT : en cas d'erreur SQL, renvoie ``{"ok": False, "error": ...}``
    SANS lever d'exception. L'agent doit alors CORRIGER sa requête à partir du
    message d'erreur et rappeler ce tool (boucle d'auto-correction).

    En cas de succès, la requête est mémorisée dans les deps pour permettre à la
    couche de délégation de créer/mettre à jour la recherche persistée.

    Args:
        sql: Requête SQL créée à partir de la requête de l'utilisateur
    """
    print("[TOOL CALL] run_sql")
    print(f"SQL: {sql}")
    try:
        rows = await asyncio.to_thread(execute_select, sql)
    except Exception as e:
        return {"ok": False, "error": str(e)}

    ctx.deps.last_sql = sql
    ctx.deps.last_count = len(rows)
    return {"ok": True, "count": len(rows)}


async def run_stats_sql(ctx: RunContext[ChatDeps], sql: str) -> dict:
    """
    Exécute une requête SQL d'agrégation (statistiques) pour la VALIDER, et renvoie
    le nombre de lignes agrégées, les colonnes calculées et un échantillon du résultat.

    IMPORTANT : en cas d'erreur SQL, renvoie ``{"ok": False, "error": ...}`` SANS lever
    d'exception. L'agent doit alors CORRIGER sa requête à partir du message d'erreur et
    rappeler ce tool (boucle d'auto-correction).

    En cas de succès, la requête est mémorisée dans les deps : c'est elle qui sera
    affichée à l'utilisateur par la couche de délégation.

    Args:
        sql: Requête SQL d'agrégation construite à partir de la demande de l'utilisateur
    """
    print("[TOOL CALL] run_stats_sql")
    print(f"SQL: {sql}")
    try:
        rows = await asyncio.to_thread(execute_select, sql)
    except Exception as e:
        return {"ok": False, "error": str(e)}

    columns = list(rows[0].keys()) if rows else []

    ctx.deps.last_stats_sql = sql
    ctx.deps.last_result = rows
    ctx.deps.last_stats_columns = columns
    # Toute nouvelle requête invalide la présentation décrite pour la précédente :
    # l'agent doit rappeler `set_statistic_presentation`.
    ctx.deps.graph_type = None
    ctx.deps.labels = None

    return {
        "ok": True,
        "count": len(rows),
        "columns": columns,
        # Échantillon (valeurs converties en texte : dates / Decimal ne sont pas
        # sérialisables telles quelles vers le modèle).
        "sample": [{k: str(v) for k, v in row.items()} for row in rows[:_MAX_SAMPLE]],
    }
