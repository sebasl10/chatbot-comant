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


async def _search_term(query: str, threshold: float, use_synonyms: bool) -> dict:
    """
    Recherche les tickets proches d'UN sujet.

    Renvoie ``{"tiers": {ticket_id: 0..4}, "distances": {ticket_id: float}, "terms_used": [...]}``.
    ``tiers`` contient TOUS les tickets retenus pour ce sujet : ceux repérés lexicalement
    (tiers 0-3) et ceux qui ne doivent leur présence qu'à la proximité sémantique (tier 4).
    ``distances`` ne contient que ceux remontés par la recherche vectorielle.
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
    return {
        "tiers": {tid: lexical_tiers.get(tid, 4) for tid in all_ids},
        "distances": best_distance,
        "terms_used": terms_used,
    }


def tier_counts_for(tiers: dict[int, int], ticket_ids: list[int]) -> list[dict]:
    """
    Répartition ``[{tier, label, count}]`` des ``ticket_ids`` donnés, dans l'ordre des tiers.
    """
    counts: dict[int, int] = {}
    for tid in ticket_ids:
        tier = tiers.get(tid)
        if tier is not None:
            counts[tier] = counts.get(tier, 0) + 1
    return [
        {"tier": tier, "label": label, "count": counts.get(tier, 0)}
        for tier, label in TIER_LABELS.items()
    ]


def _combine(results: list[dict], operator: str) -> tuple[list[int], dict[int, int]]:
    """
    Fusionne les résultats de plusieurs sujets et renvoie ``(ticket_ids triés, tiers)``.

    - ``or``  : UNION — le ticket parle d'au moins un des sujets. Son rang est celui de
      son MEILLEUR sujet (le tier et la distance les plus favorables).
    - ``and`` : INTERSECTION — le ticket parle de TOUS les sujets. Son rang est celui de
      son PLUS MAUVAIS sujet : une conjonction ne vaut que par son maillon le plus faible,
      donc un ticket qui ne rattrape l'un des sujets que par proximité sémantique passe
      derrière celui qui les porte tous les deux dans son titre.
    """
    id_sets = [set(r["tiers"]) for r in results]
    if operator == "and":
        matched, pick = set.intersection(*id_sets), max
    else:
        matched, pick = set.union(*id_sets), min

    tiers: dict[int, int] = {}
    distances: dict[int, float] = {}
    for tid in matched:
        # En union, seuls les sujets qui ont trouvé le ticket décrivent sa pertinence.
        found = [r for r in results if tid in r["tiers"]]
        tiers[tid] = pick(r["tiers"][tid] for r in found)
        distances[tid] = pick(r["distances"].get(tid, float("inf")) for r in found)

    ticket_ids = sorted(matched, key=lambda tid: (tiers[tid], distances[tid]))
    return ticket_ids, tiers


async def query_tickets(
    queries: list[str],
    operator: str = "or",
    threshold: float = 0.52,
    use_synonyms: bool = True,
) -> dict:
    """
    Recherche des tickets proches d'un ou PLUSIEURS sujets, puis combine les résultats.

    Chaque sujet est cherché séparément : les synonymes et la priorité lexicale sont propres
    à chacun. C'est seulement ensuite que les jeux de tickets sont réunis ou croisés.
    """
    operator = "and" if str(operator).strip().lower() in {"and", "et"} else "or"
    terms = [q.strip() for q in queries if q and q.strip()]

    if not terms:
        return {
            "ticket_ids": [],
            "tiers": {},
            "synonyms": [],
            "count": 0,
            "tier_counts": tier_counts_for({}, []),
            "queries": [],
            "operator": operator,
        }

    results = await asyncio.gather(*(_search_term(term, threshold, use_synonyms) for term in terms))
    ticket_ids, tiers = _combine(results, operator)

    # Tous les termes réellement utilisés (sujets + synonymes), sans doublon, dans l'ordre.
    terms_used = list(dict.fromkeys(t for r in results for t in r["terms_used"]))

    tier_counts = tier_counts_for(tiers, ticket_ids)
    print(f"[SUJETS] {terms} (operateur: {operator})")
    for entry in tier_counts:
        print(f"[TIER {entry['tier']} - {entry['label']}] {entry['count']} ticket(s)")

    return {
        "ticket_ids": ticket_ids,
        "tiers": tiers,
        "synonyms": terms_used,
        "count": len(ticket_ids),
        "tier_counts": tier_counts,
        "queries": terms,
        "operator": operator,
    }


async def semantic_ticket_search(
    ctx: RunContext[ChatDeps], queries: list[str], operator: str = "or"
) -> dict:
    """
    Recherche des tickets sémantiquement proches d'un ou plusieurs sujets/thèmes.
    Renvoie la requête SQL construite, les synonymes utilisés, le count et la
    répartition du nombre de tickets par catégorie de correspondance (tier_counts).

    Args:
        queries: LISTE des sujets extraits du message, avec les mots exacts de
            l'utilisateur (sans reformulation, sans changer les majuscules). Un seul
            sujet donne une liste d'un seul élément.
            Ex: "les tickets qui parlent de cinématique" -> ["cinématique"]
            Ex: "les tickets qui parlent de cinématique ou d'annotations" -> ["cinématique", "annotations"]
        operator: Comment relier les sujets quand il y en a plusieurs.
            "or"  (défaut) : le ticket parle d'AU MOINS UN des sujets (union) —
                  c'est le cas de "cinématique OU annotations", et d'une énumération.
            "and" : le ticket parle de TOUS les sujets à la fois (intersection) —
                  c'est le cas de "cinématique ET annotations".
            Avec un seul sujet, ce paramètre n'a aucun effet.

    Returns:
        dict avec les clés:
        - sql_query: requête SQL au format SELECT t.id, t.summary, t.description FROM ticket t WHERE t.id IN (<ids>)
        - synonyms: liste de tous les termes utilisés (sujets + synonymes)
        - count: nombre de tickets trouvés
        - tier_counts: liste de {tier, label, count}, du plus littéral (tier 0 : terme dans
          le titre) au plus sémantique (tier 4 : proximité sémantique pure)
        - queries: les sujets réellement cherchés
        - operator: l'opérateur réellement appliqué ("or" ou "and")
    """
    print("[TOOL CALL] semantic_ticket_search")
    print(f"Queries: {queries} (operator: {operator})")

    result = await query_tickets(queries, operator)
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
        "queries": result["queries"],
        "operator": result["operator"],
    }


async def semantic_ticket_filter(
    ctx: RunContext[ChatDeps], queries: list[str], operator: str = "or"
) -> dict:
    """
    Calcule le FILTRE sémantique correspondant à un ou plusieurs thèmes/sujets, à combiner
    avec des filtres exacts dans une même requête SQL (recherche hybride).

    Renvoie un fragment SQL à recopier TEL QUEL dans la clause WHERE, jeton compris :
    `{{SEMANTIC_IDS}}` est un marqueur remplacé automatiquement par la liste des tickets
    au moment de l'exécution. Ne le remplace jamais, ne le réécris jamais, n'essaie pas
    de deviner les identifiants. Le fragment reste le MÊME quel que soit le nombre de
    thèmes : la combinaison est faite ici, pas dans ta requête SQL.

    Args:
        queries: LISTE des thèmes extraits du message, avec les mots exacts de
            l'utilisateur, SANS les critères structurés (ni client, ni projet, ni
            utilisateur, ni statut, ni date). Un seul thème donne une liste d'un élément.
            Ex: "les tickets du client TPC qui parlent d'annotations 3D" -> ["annotations 3D"]
            Ex: "les tickets de TPC qui parlent de cinématique ou d'annotations"
                -> ["cinématique", "annotations"]
        operator: Comment relier les thèmes quand il y en a plusieurs.
            "or"  (défaut) : le ticket parle d'AU MOINS UN des thèmes (union).
            "and" : le ticket parle de TOUS les thèmes à la fois (intersection).
            Avec un seul thème, ce paramètre n'a aucun effet.

    Cet outil NE FAIT PAS la recherche : il ne fait que préparer un filtre. L'étape
    suivante est TOUJOURS de construire la requête SQL complète puis d'appeler `run_sql`.

    Returns:
        dict avec les clés:
        - filter_sql: fragment à insérer dans le WHERE, ex: `t.id IN ({{SEMANTIC_IDS}})`
        - synonyms: liste de tous les termes utilisés (thèmes + synonymes)
        - queries: les thèmes réellement cherchés
        - operator: l'opérateur réellement appliqué ("or" ou "and")
        - next_step: l'action à effectuer immédiatement après cet appel
    """
    print("[TOOL CALL] semantic_ticket_filter")
    print(f"Queries: {queries} (operator: {operator})")

    result = await query_tickets(queries, operator)
    ticket_ids = result["ticket_ids"]

    print(f"[NB TICKETS AVANT FILTRES] {len(ticket_ids)}")

    ctx.deps.semantic_ticket_ids = ticket_ids
    ctx.deps.semantic_terms = result["synonyms"]
    ctx.deps.semantic_tiers = result["tiers"]

    return {
        "filter_sql": f"t.id IN ({SEMANTIC_IDS_TOKEN})",
        "synonyms": result["synonyms"],
        "queries": result["queries"],
        "operator": result["operator"],
        "next_step": (
            "Filtre sémantique prêt, mais AUCUN ticket n'a encore été cherché. "
            "Construis maintenant la requête SQL complète en combinant les filtres exacts "
            f"et `AND t.id IN ({SEMANTIC_IDS_TOKEN})`, puis appelle `run_sql`. "
            "Ne réponds pas à l'utilisateur avant que `run_sql` ait réussi."
        ),
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
