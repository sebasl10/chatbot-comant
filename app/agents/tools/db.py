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
    ctx.deps.graph_type = None
    ctx.deps.labels = None
    # Une nouvelle requête principale invalide la requête externe qui lui était jointe.
    ctx.deps.external_sql = None
    ctx.deps.external_result = None
    ctx.deps.external_columns = []

    return {"ok": True, "count": len(rows)}


async def run_external_sql(ctx: RunContext[ChatDeps], sql: str) -> dict:
    """
    Exécute une requête d'agrégation sur la base EXTERNE (absences, table `days`) pour la
    VALIDER. À n'utiliser que si la statistique demandée porte sur les absences, et
    TOUJOURS après un `run_stats_sql` réussi.

    Le résultat de cette requête sera fusionné avec celui de la requête principale sur
    leurs colonnes COMMUNES (la clé de jointure). Cette requête doit donc renvoyer :
    - la ou les colonnes de regroupement de la requête principale, avec le MÊME alias
      (ex: `d.uid AS username`) ;
    - au moins une colonne de valeurs qui n'existe pas dans la requête principale.

    IMPORTANT : en cas d'erreur, renvoie ``{"ok": False, "error": ...}`` SANS lever
    d'exception. Corrige la requête à partir du message et rappelle ce tool.

    Args:
        sql: Requête SQL d'agrégation sur la base externe
    """
    print("[TOOL CALL] run_external_sql")
    print(f"SQL: {sql}")

    if not ctx.deps.last_stats_sql:
        return {
            "ok": False,
            "error": "Aucune requête principale validée : appelle d'abord `run_stats_sql`, "
            "car la requête externe doit reprendre ses colonnes de regroupement.",
        }

    try:
        rows = await asyncio.to_thread(execute_select, sql, "external")
    except Exception as e:
        return {"ok": False, "error": str(e)}

    columns = list(rows[0].keys()) if rows else []
    main_columns = ctx.deps.last_stats_columns
    join_keys = [c for c in columns if c in main_columns]
    new_columns = [c for c in columns if c not in main_columns]

    if not join_keys:
        return {
            "ok": False,
            "error": f"Aucune colonne commune avec la requête principale : la fusion est "
            f"impossible. Colonnes principales : {main_columns}, colonnes externes : "
            f"{columns}. Reprends l'alias de la colonne de regroupement "
            f"(ex: `d.uid AS {main_columns[0] if main_columns else 'username'}`).",
        }
    if not new_columns:
        return {
            "ok": False,
            "error": f"La requête externe n'apporte aucune colonne nouvelle : {columns}. "
            f"Elle doit calculer l'indicateur absent de la requête principale "
            f"(ex: `AS secondes_absence`).",
        }

    ctx.deps.external_sql = sql
    ctx.deps.external_result = rows
    ctx.deps.external_columns = columns
    ctx.deps.graph_type = None
    ctx.deps.labels = None

    return {"ok": True, "count": len(rows), "cle_de_jointure": join_keys}
