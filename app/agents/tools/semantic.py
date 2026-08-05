"""
Tool de recherche sémantique de tickets (backed Chroma).
"""

import asyncio

from pydantic_ai import RunContext

from app.agents.deps import ChatDeps
from app.services import vectorstore as vs
from app.services.database import get_connection

# ── Priorité lexicale (SQL) sur la recherche sémantique ─────────────────────
# Ordre de priorité des tickets, du plus littéral au plus sémantique :
#   0. le terme cherché apparaît dans le titre (summary)
#   1. le terme cherché apparaît dans la description ou un commentaire
#   2. un synonyme (vocabulaire lié) apparaît dans le titre
#   3. un synonyme apparaît dans la description ou un commentaire
#   4. aucun match lexical, seulement une proximité sémantique sous le seuil

TIER_LABELS = {
    0: "terme dans le titre",
    1: "terme dans description/commentaires",
    2: "terme lié dans le titre",
    3: "terme lié dans description/commentaires",
    4: "sémantiquement proches",
}

# Jeton laissé par `semantic_ticket_filter` dans le fragment SQL rendu à l'agent
# hybride. La liste réelle des ids (potentiellement des milliers) ne transite jamais
# par le LLM : elle est substituée juste avant l'exécution (cf. `app/agents/tools/db.py`).
SEMANTIC_IDS_TOKEN = "{{SEMANTIC_IDS}}"


def _like_clause(column: str, terms: list[str]) -> tuple[str, list[str]]:
    """Construit ``(column LIKE %s OR column LIKE %s ...)`` pour une liste de termes."""
    clean_terms = [t.strip() for t in terms if t and t.strip()]
    condition = " OR ".join([f"{column} LIKE %s"] * len(clean_terms))
    params = [f"%{t}%" for t in clean_terms]
    return f"({condition})", params


def _fetch_lexical_tiers(base_term: str, synonyms: list[str]) -> dict[int, int]:
    """
    Renvoie ``{ticket_id: tier}`` (0 à 3, cf. TIER_LABELS) selon que le terme de
    base ou un synonyme apparaît dans le titre, la description ou un commentaire
    (sous-chaîne, ``LIKE``). Bloquant (pymysql) : à appeler via ``asyncio.to_thread``.
    """
    subqueries: list[str] = []
    params: list[str] = []

    type_condition = "t.type IN ('Bug', 'Dev', 'Suggestion', 'Requête', 'Documentation')"
    comment_type_filter = "c.ticket_id IN (SELECT id FROM ticket WHERE type IN ('Bug', 'Dev', 'Suggestion', 'Requête', 'Documentation'))"

    cond, p = _like_clause("t.summary", [base_term])
    subqueries.append(
        f"SELECT t.id AS ticket_id, 0 AS tier FROM ticket t WHERE {cond} AND {type_condition}"
    )
    params += p

    cond, p = _like_clause("t.description", [base_term])
    subqueries.append(
        f"SELECT t.id AS ticket_id, 1 AS tier FROM ticket t WHERE {cond} AND {type_condition}"
    )
    params += p

    cond, p = _like_clause("c.text", [base_term])
    subqueries.append(
        f"SELECT c.ticket_id AS ticket_id, 1 AS tier FROM comment c WHERE {cond} AND {comment_type_filter}"
    )
    params += p

    if synonyms:
        cond, p = _like_clause("t.summary", synonyms)
        subqueries.append(
            f"SELECT t.id AS ticket_id, 2 AS tier FROM ticket t WHERE {cond} AND {type_condition}"
        )
        params += p

        cond, p = _like_clause("t.description", synonyms)
        subqueries.append(
            f"SELECT t.id AS ticket_id, 3 AS tier FROM ticket t WHERE {cond} AND {type_condition}"
        )
        params += p

        cond, p = _like_clause("c.text", synonyms)
        subqueries.append(
            f"SELECT c.ticket_id AS ticket_id, 3 AS tier FROM comment c WHERE {cond} AND {comment_type_filter}"
        )
        params += p

    sql = (
        "SELECT ticket_id, MIN(tier) AS tier FROM (\n            "
        + "\n            UNION ALL\n            ".join(subqueries)
        + "\n        ) x GROUP BY ticket_id"
    )

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
    finally:
        conn.close()

    return {row["ticket_id"]: row["tier"] for row in rows}


async def query_tickets(query: str, threshold: float = 0.52, use_synonyms: bool = True) -> dict:
    """
    Recherche des tickets sémantiquement proches de la query.
    Récupère toujours 3000 résultats puis filtre ceux avec distance <= threshold.
    Priorise ensuite par tier lexical (cf. ``_fetch_lexical_tiers``) : terme dans le
    titre > terme dans description/commentaires > synonyme dans le titre > synonyme
    dans description/commentaires > proximité purement sémantique.
    """
    col = await vs.tickets_collection()

    query_instruction = "Given a technical term or topic, retrieve support tickets that mention or relate to it, even briefly."

    all_embeddings = []
    terms_used = []
    synonyms: list[str] = []

    if use_synonyms:
        synonyms = (await vs.get_vocabulary_for_term(query))["synonyms"]
        if synonyms:
            all_terms = [query] + synonyms
            prompts = [f"Instruct: {query_instruction}\nQuery: {term}" for term in all_terms]
            all_embeddings = await vs.get_embeddings(prompts)
            terms_used = all_terms

    if not all_embeddings:
        all_embeddings = await vs.get_embeddings([f"Instruct: {query_instruction}\nQuery: {query}"])
        terms_used = [query]

    res = await col.query(query_embeddings=all_embeddings, n_results=3000, include=["distances"])

    all_results = []
    for i in range(len(all_embeddings)):
        ids = res["ids"][i]
        distances = res["distances"][i]
        for j in range(len(ids)):
            all_results.append(
                {
                    "id": int(ids[j]),
                    "distance": distances[j],
                }
            )

    all_results.sort(key=lambda x: x["distance"])
    filtered_results = [r for r in all_results if r["distance"] <= threshold]

    # Meilleure distance connue par ticket (les résultats sont déjà triés par distance croissante).
    best_distance: dict[int, float] = {}
    for r in filtered_results:
        best_distance.setdefault(r["id"], r["distance"])

    # Priorité lexicale (tiers 0-3, cf. _fetch_lexical_tiers) devant les résultats
    # purement sémantiques (tier 4), même si leur score de similarité est moins bon.
    lexical_tiers = await asyncio.to_thread(_fetch_lexical_tiers, query, synonyms)

    all_ids = set(best_distance) | set(lexical_tiers)
    ticket_ids = sorted(
        all_ids,
        key=lambda tid: (lexical_tiers.get(tid, 4), best_distance.get(tid, float("inf"))),
    )

    tier_counts: dict[int, int] = {}
    for tid in all_ids:
        tier = lexical_tiers.get(tid, 4)
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
    for tier, label in TIER_LABELS.items():
        print(f"[TIER {tier} - {label}] {tier_counts.get(tier, 0)} ticket(s)")

    return {
        "ticket_ids": ticket_ids,
        "synonyms": terms_used,
        "count": len(ticket_ids),
        "tier_counts": [
            {"tier": tier, "label": label, "count": tier_counts.get(tier, 0)}
            for tier, label in TIER_LABELS.items()
        ],
    }


async def semantic_ticket_search(ctx: RunContext[ChatDeps], query: str) -> dict:
    """
    Recherche des tickets sémantiquement proches de `query` (sujet/thème).
    Renvoie la requête SQL construite, les synonymes utilisés, le count et la
    répartition du nombre de tickets par catégorie de correspondance (tier_counts).

    Args:
        query: Message exact envoyé par l'utilisateur, sans modification, sans reformulation, sans ajout de texte

    Returns:
        dict avec les clés:
        - sql_query: requête SQL au format SELECT t.id, t.summary, t.description FROM ticket t WHERE t.id IN (<ids>)
        - synonyms: liste de tous les termes utilisés (query + synonymes)
        - count: nombre de tickets trouvés
        - tier_counts: liste de {tier, label, count}, du plus littéral (tier 0 : terme dans
          le titre) au plus sémantique (tier 4 : proximité sémantique pure)
    """
    print("[TOOL CALL] semantic_ticket_search")
    print(f"Query: {query}")

    result = await query_tickets(query)
    ticket_ids = result["ticket_ids"]
    if ticket_ids:
        ids_str = ", ".join(str(tid) for tid in ticket_ids)
        sql_query = (
            f"SELECT t.id, t.summary, t.description FROM ticket t WHERE t.id IN ({ids_str}) "
        )
    else:
        sql_query = "SELECT t.id, t.summary, t.description FROM ticket t WHERE t.id IN ()"

    print(f"[SQL RESULT] {sql_query}")
    print(f"[NB TICKETS] {len(ticket_ids)}")

    ctx.deps.last_sql = sql_query
    ctx.deps.last_count = len(ticket_ids)

    return {
        "sql_query": sql_query,
        "synonyms": result["synonyms"],
        "count": result["count"],
        "tier_counts": result["tier_counts"],
    }


async def semantic_ticket_filter(ctx: RunContext[ChatDeps], query: str) -> dict:
    """
    Calcule le FILTRE sémantique correspondant à un thème/sujet, à combiner avec des
    filtres exacts dans une même requête SQL (recherche hybride).

    Renvoie un fragment SQL à recopier TEL QUEL dans la clause WHERE, jeton compris :
    `{{SEMANTIC_IDS}}` est un marqueur remplacé automatiquement par la liste des tickets
    au moment de l'exécution. Ne le remplace jamais, ne le réécris jamais, n'essaie pas
    de deviner les identifiants.

    Args:
        query: le thème/sujet extrait du message, SANS les critères structurés
               (ex: "annotations 3D" pour "les tickets du client TPC qui parlent
               d'annotations 3D")

    Returns:
        dict avec les clés:
        - filter_sql: fragment à insérer dans le WHERE, ex: `t.id IN ({{SEMANTIC_IDS}})`
        - count_before_filters: nombre de tickets correspondant au thème AVANT
          application des filtres exacts (à ne pas annoncer à l'utilisateur)
        - synonyms: liste de tous les termes utilisés (query + synonymes)
    """
    print("[TOOL CALL] semantic_ticket_filter")
    print(f"Query: {query}")

    result = await query_tickets(query)
    ticket_ids = result["ticket_ids"]

    print(f"[NB TICKETS AVANT FILTRES] {len(ticket_ids)}")

    ctx.deps.semantic_ticket_ids = ticket_ids
    ctx.deps.semantic_terms = result["synonyms"]

    return {
        "filter_sql": f"t.id IN ({SEMANTIC_IDS_TOKEN})",
        "count_before_filters": result["count"],
        "synonyms": result["synonyms"],
    }


async def get_vocabulary_for_term(ctx: RunContext[ChatDeps], term: str) -> dict:
    """
    Récupère le vocabulaire (synonymes) associé à un terme donné avec ses métadonnées.
    Utilisé pour répondre à des questions comme :
    - "Quel est le vocabulaire que tu connais pour X ?"
    - "Quels sont les termes liés à X ?"
    - "Qui a ajouté le terme X ?"
    - "Qui t'a dit que X doit être inclus ?"

    Args:
        term: Le terme de base pour lequel on veut récupérer les synonymes

    Returns:
        dict avec les clés:
        - base_term: le terme de base
        - synonyms: liste des synonymes/termes liés
        - metadata: dict avec username, date, user_id, etc. (ou None)
        - count: nombre de synonymes trouvés
    """
    print("[TOOL CALL] get_vocabulary_for_term")
    print(f"Term: {term}")

    result = await vs.get_vocabulary_for_term(term)
    print(f"[RESULTS] Vocabulaire pour '{term}': {result}")

    return result


async def remove_term_from_vocabulary(ctx: RunContext[ChatDeps], term: str, base_term: str) -> dict:
    """
    Supprime un terme spécifique du vocabulaire associé à un terme de base.
    Utilisé pour répondre à des questions comme :
    - "supprime X du vocabulaire lié à Y"
    - "X ne doit pas être lié à Y"

    Args:
        term: Le terme à supprimer (ex: "lent")
        base_term: Le terme de base dont on veut supprimer le synonyme (ex: "performance")

    Returns:
        dict avec les clés:
        - success: bool indiquant si la suppression a réussi
        - message: message de confirmation ou d'erreur
        - base_term: le terme de base
        - removed_term: le terme supprimé
    """
    print("[TOOL CALL] remove_term_from_vocabulary")
    print(f"Term to remove: {term}, Base term: {base_term}")

    result = await vs.remove_term_from_vocabulary(term, base_term)
    print(f"[RESULTS] Suppression de '{term}' du vocabulaire de '{base_term}': {result}")

    return result
