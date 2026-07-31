import calendar
import datetime
import json
import re

import pymysql

from app.config import settings

def get_connection(db: str = 'comant'):
    try:
        if db == 'external':
            return pymysql.connect(host=settings.external_db_host, port=settings.external_db_port, database=settings.external_db_name, user=settings.external_db_user, password=settings.external_db_password, charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)
        else:
            return pymysql.connect(host=settings.db_host, port=settings.db_port, database=settings.db_name, user=settings.db_user, password=settings.db_password, charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,)
    except pymysql.Error as e:
        raise RuntimeError(f"Erreur de connexion à la base de données : {e}")


# Recupère les tables et colonnes réelles depuis la base
def get_db_schema():
    conn = get_connection()
    schema = {"tables": {}}

    try:
        with conn.cursor() as cursor:
            # Récupère les tables
            cursor.execute(f"SHOW TABLES FROM {settings.db_name}")
            result = cursor.fetchall()
            tables = [list(row.values())[0] for row in result]

            for table in tables:
                cursor.execute(f"DESCRIBE {table}")
                columns = cursor.fetchall()
                table_info = {"columns": {}}

                for col in columns:
                    col_name = col["Field"]
                    col_type = col["Type"]
                    is_nullable = col["Null"] == "YES"
                    is_primary_key = col["Key"] == "PRI"

                    col_info = {
                        "type": col_type,
                        "nullable": is_nullable,
                        "primary_key": is_primary_key,
                    }

                    # Détecter les clés étrangères (simplifié)
                    if col_name.endswith("_id") and col_name != "id":
                        referenced_table = col_name.replace("_id", "")
                        if referenced_table in tables:
                            col_info["foreign_key"] = f"{referenced_table}.id"

                    table_info["columns"][col_name] = col_info

                schema["tables"][table] = table_info

            # Récupérer les relations (clés étrangères)
            cursor.execute(
                """
                SELECT TABLE_NAME, COLUMN_NAME, REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME
                FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
                WHERE TABLE_SCHEMA = %s AND REFERENCED_TABLE_NAME IS NOT NULL
            """,
                (settings.db_name,),
            )

            relations = cursor.fetchall()
            for rel in relations:
                table_name = rel["TABLE_NAME"]
                column_name = rel["COLUMN_NAME"]
                referenced_table = rel["REFERENCED_TABLE_NAME"]
                referenced_column = rel["REFERENCED_COLUMN_NAME"]

                if (
                    table_name in schema["tables"]
                    and column_name in schema["tables"][table_name]["columns"]
                ):
                    schema["tables"][table_name]["columns"][column_name]["foreign_key"] = (
                        f"{referenced_table}.{referenced_column}"
                    )

    finally:
        conn.close()

    return json.dumps(schema, indent=2, ensure_ascii=False)


def execute_select(sql: str) -> list[dict]:
    re.sub(r"[^\x20-\x7E]", "", sql)
    sql_clean = sql.strip().upper()

    if not sql_clean.startswith("SELECT"):
        raise ValueError("Seules les requêtes SELECT sont autorisées")

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql)
            return cursor.fetchall()
    except Exception as e:
        print(f"Erreur lors de l'exécution de la requête : {e}")
        print(f"Requête problématique : {repr(sql)}")
        raise
    finally:
        conn.close()


def update_intention(last_message_id: int, intention: str):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE message SET intention = %s WHERE id = %s", (intention, last_message_id)
            )
            conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def update_conversation_name(conversation_id: int, name: str):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE conversation SET name = %s WHERE id = %s", (name, conversation_id)
            )
            conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def create_research(user_id: int, sql: str, isSemantic: bool = False) -> int:
    now = datetime.datetime.now()
    name = f"Recherche_{now.strftime('%Y-%m-%d_%H-%M-%S')}"
    defaultColumns = [
        "Type/Priorité",
        "Code",
        "Statut",
        "Titre",
        "Tags",
        "Projets",
        "Produit",
        "Composant",
        "Assigné(e)",
        "Créateur",
        "Modifié le",
    ]
    defaultColumns_json = json.dumps(defaultColumns, ensure_ascii=False)

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            query = """
                INSERT INTO research (creator_id, name, filters, columns, sql_request, is_semantic)
                VALUES (%s, %s, '[]', %s, %s, %s)
            """
            cursor.execute(query, (user_id, name, defaultColumns_json, sql, isSemantic))
            conn.commit()
            research_id = cursor.lastrowid
            return research_id
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def update_sql(last_message_id: int, sql: str, research_id: int) -> int:
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            if research_id == 0:
                cursor.execute("SELECT research_id FROM message WHERE id = %s", (last_message_id,))
                result = cursor.fetchone()

                if result is None:
                    raise ValueError(f"Aucun message trouvé avec l'ID {last_message_id}")

                research_id = result["research_id"]

                if research_id is None:
                    raise ValueError(f"Le message {last_message_id} n'a pas de research_id associé")

            cursor.execute("UPDATE research SET sql_request = %s WHERE id = %s", (sql, research_id))
            conn.commit()
            return research_id
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def get_sql(research_id: int) -> str:
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cursor:
            query = "SELECT sql_request FROM research WHERE id = %s"
            cursor.execute(query, (research_id,))
            result = cursor.fetchone()
            if result is None:
                raise ValueError(f"Aucune requête SQL trouvée pour l'ID {research_id}")
            return result["sql_request"]
    except Exception as e:
        if conn:
            conn.rollback()
        raise e
    finally:
        if conn:
            conn.close()


def rename_research(research_id: int, name: str, user_id: int | None = None) -> None:
    """
    Renomme une recherche (équivaut à « sauvegarder »).
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            if user_id is not None:
                cursor.execute(
                    "UPDATE research SET name = %s, saved = %s WHERE id = %s AND creator_id = %s",
                    (name, True, research_id, user_id),
                )
            else:
                cursor.execute(
                    "UPDATE research SET name = %s, saved = %s WHERE id = %s",
                    (name, True, research_id),
                )
            conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def delete_research(research_id: int, user_id: int | None = None) -> None:
    """Supprime une recherche. Restreint au créateur si ``user_id`` est fourni."""
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            if user_id is not None:
                cursor.execute(
                    "DELETE FROM research WHERE id = %s AND creator_id = %s",
                    (research_id, user_id),
                )
            else:
                cursor.execute("DELETE FROM research WHERE id = %s", (research_id,))
            conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def get_username(user_id: int) -> str:
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT username FROM user WHERE id = %s", (user_id,))
            result = cursor.fetchone()
            if result:
                return result["username"]
            return None
    except Exception as e:
        print(f"Erreur lors de la récupération du username pour l'ID {user_id}: {e}")
        return None
    finally:
        conn.close()
        
def is_admin(user_id: int) -> bool:
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT roles FROM user WHERE id = %s", (user_id,))
            result = cursor.fetchone()
            if result:
                roles = result["roles"]
                if isinstance(roles, str):
                    roles_list = json.loads(roles)
                else:
                    roles_list = roles
                return "ROLE_ADMIN" in roles_list
            return False
    except Exception as e:
        print(f"Erreur lors de la récupération du username pour l'ID {user_id}: {e}")
        return None
    finally:
        conn.close()
       
def create_statistic(user_id: int, sql: str, graph_type: str, description: str, labels: str | None, external_sql: str | None = None, last_result : str | None = None) -> int:
    now = datetime.datetime.now()
    name = f"Statistique_{now.strftime('%Y-%m-%d_%H-%M-%S')}"

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            query = """
                INSERT INTO statistics (creator_id, name, created_at, sql_request, external_sql_request, last_result, graph_type, labels, description)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            cursor.execute(query, (user_id, name, now, sql, external_sql, last_result, graph_type, labels, description))
            conn.commit()
            statistic_id = cursor.lastrowid
            return statistic_id
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def get_absences(user: str, year: int = None, month: int = None, min_date: str = None, max_date: str = None) -> list[dict] | None:
    conn = get_connection('external')
    try:
        base_sql = "SELECT * FROM days WHERE uid = %s AND type <> %s"
        params = [user, 32]

        if min_date is None and max_date is None:
            if year is not None:
                if month is not None:
                    start_date = datetime.datetime(year, month, 1)
                    _, last_day = calendar.monthrange(year, month)
                    end_date = datetime.datetime(year, month, last_day)
                    base_sql += " AND date BETWEEN %s AND %s"
                    params.extend([start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d')])
                else:
                    base_sql += " AND date BETWEEN %s AND %s"
                    params.extend([f"{year}-01-01", f"{year}-12-31"])
        else:
            if min_date is not None:
                base_sql += " AND date >= %s"
                params.append(min_date)
            if max_date is not None:
                base_sql += " AND date <= %s"
                params.append(max_date)

        with conn.cursor() as cursor:
            cursor.execute(base_sql, tuple(params))
            results = cursor.fetchall()
            return results if results else None
    except Exception as e:
        print(f"Erreur lors de la récupération des absences pour l'ID {user}: {e}")
        return None
    finally:
        conn.close()