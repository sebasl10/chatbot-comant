import datetime
import json
import pymysql
import re
from app.config import settings

def get_connection():
    try:
        return pymysql.connect(
            host=settings.db_host,
            port=settings.db_port,
            database=settings.db_name,
            user=settings.db_user,
            password=settings.db_password,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor
        )
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
                    col_name = col['Field']
                    col_type = col['Type']
                    is_nullable = col['Null'] == "YES"
                    is_primary_key = col['Key'] == "PRI"

                    col_info = {
                        "type": col_type,
                        "nullable": is_nullable,
                        "primary_key": is_primary_key
                    }

                    # Détecter les clés étrangères (simplifié)
                    if col_name.endswith("_id") and col_name != "id":
                        referenced_table = col_name.replace("_id", "")
                        if referenced_table in tables:
                            col_info["foreign_key"] = f"{referenced_table}.id"

                    # Ajouter les valeurs possibles pour certaines colonnes
                    """ if table == "log" and col_name == "action":
                        col_info["allowed_values"] = [
                            "VIEW-PROJECT", "VIEW-TICKET", "EDIT-TICKET",
                            "CREATE-TICKET", "DELETE-TICKET", "COMMENT-TICKET"
                        ]
                    elif table == "ticket" and col_name == "status":
                        col_info["allowed_values"] = ["open", "closed", "in_progress", "pending"]
                    """

                    table_info["columns"][col_name] = col_info

                schema["tables"][table] = table_info

            # Récupérer les relations (clés étrangères)
            cursor.execute("""
                SELECT TABLE_NAME, COLUMN_NAME, REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME
                FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
                WHERE TABLE_SCHEMA = %s AND REFERENCED_TABLE_NAME IS NOT NULL
            """, (settings.db_name,))

            relations = cursor.fetchall()
            for rel in relations:
                table_name = rel['TABLE_NAME']
                column_name = rel['COLUMN_NAME']
                referenced_table = rel['REFERENCED_TABLE_NAME']
                referenced_column = rel['REFERENCED_COLUMN_NAME']

                if table_name in schema["tables"] and column_name in schema["tables"][table_name]["columns"]:
                    schema["tables"][table_name]["columns"][column_name]["foreign_key"] = f"{referenced_table}.{referenced_column}"

    finally:
        conn.close()

    return json.dumps(schema, indent=2, ensure_ascii=False)

def execute_select(sql: str, research_id: int, user_id: int) -> list[dict]:
    re.sub(r'[^\x20-\x7E]', '', sql)
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
                "UPDATE message SET intention = %s WHERE id = %s",
                (intention, last_message_id)
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
                "UPDATE conversation SET name = %s WHERE id = %s",
                (name, conversation_id)
            )
            conn.commit()
    except Exception as e:
        conn.rollback() 
        raise e
    finally:
        conn.close()

def create_research(user_id: int, sql: str) -> int:
    now = datetime.datetime.now()
    name = f"Recherche_{now.strftime('%Y-%m-%d_%H-%M-%S')}"
    defaultColumns = ["Type/Priorité", "Code", "Statut", "Titre", "Tags", "Projets", "Produit", "Composant", "Assigné(e)", "Créateur", "Modifié le"]
    defaultColumns_json = json.dumps(defaultColumns, ensure_ascii=False)

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            query = f"""
                INSERT INTO research (creator_id, name, filters, columns, sql_request)
                VALUES (%s, %s, '[]', %s, %s)
            """
            cursor.execute(query, (user_id, name, defaultColumns_json, sql))
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
            if (research_id == 0):
                cursor.execute("SELECT research_id FROM message WHERE id = %s", (last_message_id,))
                result = cursor.fetchone()

                if result is None:
                    raise ValueError(f"Aucun message trouvé avec l'ID {last_message_id}")

                research_id = result['research_id']

                if research_id is None:
                    raise ValueError(f"Le message {last_message_id} n'a pas de research_id associé")

            cursor.execute(
                "UPDATE research SET sql_request = %s WHERE id = %s",
                (sql, research_id)
            )
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
            return result['sql_request'] 
    except Exception as e:
        if conn:
            conn.rollback()
        raise e 
    finally:
        if conn:
            conn.close()

def rename_research(research_id: int, name: str, user_id: int | None = None) -> None:
    """Renomme une recherche (équivaut à « sauvegarder »). Si ``user_id`` est
    fourni, la mise à jour est restreinte au créateur (sécurité)."""
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            if user_id is not None:
                cursor.execute(
                    "UPDATE research SET name = %s WHERE id = %s AND creator_id = %s",
                    (name, research_id, user_id),
                )
            else:
                cursor.execute("UPDATE research SET name = %s WHERE id = %s", (name, research_id))
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


def get_finetuning_triplets() -> list[dict]:
    conn = get_connection()   
    cursor = conn.cursor()    
    cursor.execute("""       
        SELECT
            u.content AS input,
            b.generated_sql AS rejected,
            b.correct_sql AS chosen,
            c.user_id AS user_id
        FROM message u
        JOIN conversation c
            ON u.conversation_id = c.id
        JOIN LATERAL (
            SELECT generated_sql, sql_status, feedback, correct_sql
            FROM message
            WHERE conversation_id = u.conversation_id
            AND sender_role = 'bot'
            AND created_at > u.created_at
            ORDER BY created_at ASC
            LIMIT 1
        ) b ON true
        WHERE u.sender_role = 'user'
        AND u.intention = 'recherche'
        AND b.generated_sql IS NOT NULL
        AND b.correct_sql IS NOT NULL
        AND b.feedback = 'dislike';
    """)    
    rows = cursor.fetchall()   
    cursor.close()    
    conn.close()   
    return rows

def get_finetuning_couples() -> list[dict]:
    conn = get_connection()   
    cursor = conn.cursor()    
    cursor.execute("""       
        SELECT
            u.content AS input,
            CASE
                WHEN b.feedback = 'like' THEN b.generated_sql
                WHEN b.feedback = 'dislike' THEN b.correct_sql
            END AS label,
            c.user_id AS user_id
        FROM message u
        JOIN conversation c ON u.conversation_id = c.id
        JOIN LATERAL (
            SELECT generated_sql, correct_sql, feedback, sql_status
            FROM message
            WHERE conversation_id = u.conversation_id
            AND sender_role = 'bot'
            AND created_at > u.created_at
            ORDER BY created_at ASC
            LIMIT 1
        ) b ON true
        WHERE u.sender_role = 'user'
        AND u.intention = 'recherche'
        AND (
            (b.feedback = 'like' AND b.generated_sql IS NOT NULL)
            OR
            (b.feedback = 'dislike' AND b.correct_sql IS NOT NULL)
        );
    """)    
    rows = cursor.fetchall()   
    cursor.close()    
    conn.close()   
    return rows

def get_username(user_id: int) -> str:
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT username FROM user WHERE id = %s", (user_id,))
            result = cursor.fetchone()
            if result:
                return result['username']
            return None
    except Exception as e:
        print(f"Erreur lors de la récupération du username pour l'ID {user_id}: {e}")
        return None
    finally:
        conn.close()
