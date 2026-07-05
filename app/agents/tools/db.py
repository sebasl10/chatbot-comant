"""Tools base de données (LangChain) : schéma + exécution SQL auto-corrective.

Variante LangGraph des tools ``db`` : mêmes appels aux services, mais déclarés en
tools LangChain (``@tool``) et lisant ``ChatDeps`` via ``config``.
Appels bloquants (pymysql) déportés sur un thread.
"""
import asyncio

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.agents.context import deps_from_config
from app.services.database import get_db_schema, execute_select

_MAX_SAMPLE = 5


@tool
async def db_schema(config: RunnableConfig) -> str:
    """Retourne le schéma de la base (tables, colonnes, types, clés étrangères)
    au format JSON. À appeler avant d'écrire une requête SQL."""
    return await asyncio.to_thread(get_db_schema)


@tool
async def run_sql(sql: str, config: RunnableConfig) -> dict:
    """Exécute une requête SELECT et renvoie le nombre de résultats + un échantillon.

    IMPORTANT : en cas d'erreur SQL, renvoie ``{"ok": false, "error": ...}`` SANS
    lever d'exception. Corrige alors ta requête à partir du message d'erreur et
    rappelle ce tool (boucle d'auto-correction, 2 corrections max).

    En cas de succès, la requête est mémorisée pour la persistance de la recherche.
    """
    deps = deps_from_config(config)
    try:
        rows = await asyncio.to_thread(execute_select, sql, "", deps.user_id)
    except Exception as e:  # ValueError (non-SELECT) ou erreur pymysql
        return {"ok": False, "error": str(e)}

    deps.last_sql = sql
    deps.last_count = len(rows)
    return {"ok": True, "count": len(rows), "sample": rows[:_MAX_SAMPLE]}
