"""Tools base de données : schéma + exécution SQL avec boucle d'auto-correction.

Ces fonctions sont enregistrées comme tools Pydantic AI sur les agents SQL.
Les appels bloquants (pymysql) sont déportés sur un thread pour ne pas figer
la boucle asyncio pendant le streaming.
"""
import asyncio

from pydantic_ai import RunContext

from app.agents.deps import ChatDeps
from app.services.database import get_db_schema, execute_select

# Nombre de lignes d'échantillon renvoyées à l'agent pour qu'il vérifie que la
# requête a du sens, sans inonder le contexte.
_MAX_SAMPLE = 5


async def db_schema(ctx: RunContext[ChatDeps]) -> str:
    """Retourne le schéma de la base (tables, colonnes, types, clés étrangères)
    au format JSON. À appeler avant d'écrire une requête SQL."""
    return await asyncio.to_thread(get_db_schema)


async def run_sql(ctx: RunContext[ChatDeps], sql: str) -> dict:
    """Exécute une requête SELECT et renvoie le nombre de résultats + un
    échantillon de lignes.

    IMPORTANT : en cas d'erreur SQL, renvoie ``{"ok": False, "error": ...}``
    SANS lever d'exception. L'agent doit alors CORRIGER sa requête à partir du
    message d'erreur et rappeler ce tool (boucle d'auto-correction).

    En cas de succès, la requête est mémorisée dans les deps pour permettre à la
    couche de délégation de créer/mettre à jour la recherche persistée.
    """
    try:
        rows = await asyncio.to_thread(execute_select, sql, "", ctx.deps.user_id)
    except Exception as e:  # ValueError (non-SELECT) ou erreur pymysql
        return {"ok": False, "error": str(e)}

    ctx.deps.last_sql = sql
    ctx.deps.last_count = len(rows)
    return {"ok": True, "count": len(rows), "sample": rows[:_MAX_SAMPLE]}
