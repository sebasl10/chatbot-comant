"""
Base vectorielle Chroma — tickets, mémoires, résumés de conversation.

Collections :
- ``tickets``                : embeddings de tickets.
- ``memories``               : souvenirs/corrections + exemples de routage, filtrables par métadonnées ``{target_agent, kind, scope, user_id}`` (``kind`` = "behavior" par défaut, "vocabulary" uniquement pour semantic_research) et recherchables sémantiquement. Guide aussi le superviseur (``target_agent=supervisor``).
- ``conversation_summaries`` : résumés de conversation.
"""

from __future__ import annotations
import asyncio
from typing import Any, Dict, List
import requests
from chromadb import AsyncHttpClient
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
import uuid
from datetime import datetime
from app.config import settings
from app.services.database import get_username, get_connection
from bs4 import BeautifulSoup

TICKETS = "tickets"
MEMORIES = "memories"
CONVERSATION_SUMMARIES = "conversation_summaries"
DEFAULT_HNSW_CONFIG = {
    "hnsw": {
        "space": "cosine",
        "max_neighbors": 32,
        "ef_construction": 1000,
        "ef_search": 1000
    }
}

class OllamaEmbeddingFunction(EmbeddingFunction):
    """
    Embeddings via l'endpoint /api/embed d'Ollama (même modèle que les tickets).
    """

    def __init__(self, url: str | None = None, model: str | None = None):
        self._url = url or settings.ollama_url_embedding
        self._model = model or settings.model_ia_embedding

    def __call__(self, input: Documents) -> Embeddings:
        resp = requests.post(
            self._url,
            json={"model": self._model, "input": list(input), "keep_alive": "30m"},
        )
        resp.raise_for_status()
        return resp.json()["embeddings"]

    @staticmethod
    def name() -> str:
        return "ollama_embed"


_client = None

# Initialiser la fonction d'embedding pour réutilisation
_embedding_function: OllamaEmbeddingFunction | None = None


def get_embedding_function() -> OllamaEmbeddingFunction:
    """
    Retourne ou initialise la fonction d'embedding.
    """
    global _embedding_function
    if _embedding_function is None:
        _embedding_function = OllamaEmbeddingFunction()
    return _embedding_function


def get_embedding(text: str) -> list[float]:
    """
    Calcule l'embedding d'un texte en utilisant le modèle configuré.

    Reste synchrone (requests) : Chroma invoque toujours sa embedding_function
    de façon synchrone, même côté AsyncCollection. Les appelants asynchrones
    doivent passer par ``asyncio.to_thread`` pour ne pas bloquer l'event loop.
    """
    emb_fn = get_embedding_function()
    embeddings = emb_fn([text])
    return embeddings[0]


async def get_embeddings(texts: list[str]) -> list[list[float]]:
    """
    Calcule les embeddings de plusieurs textes en parallèle, sans bloquer l'event loop.
    """
    return await asyncio.gather(*(asyncio.to_thread(get_embedding, t) for t in texts))


async def get_client():
    global _client
    if _client is None:
        _client = await AsyncHttpClient(host=settings.chroma_http_url)
    return _client


_collections: dict[str, Any] = {}


async def _collection(name: str):
    if name not in _collections:
        client = await get_client()
        _collections[name] = await client.get_or_create_collection(
            name, configuration=DEFAULT_HNSW_CONFIG, embedding_function=OllamaEmbeddingFunction()
        )
    return _collections[name]


async def tickets_collection():
    return await _collection(TICKETS)


async def memories_collection():
    return await _collection(MEMORIES)


async def summaries_collection():
    return await _collection(CONVERSATION_SUMMARIES)

# ── Ajouter/mettre à jouter l'embedding d'un ticket dans Chroma ────────────

def _fetch_ticket_text(ticket_id: int) -> str | None:
    """
    Récupère un ticket et ses commentaires en base et construit le texte complet.
    Bloquant (pymysql) : à appeler via ``asyncio.to_thread``.
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()

        cursor.execute("SELECT id, summary, description FROM ticket WHERE id = %s", (ticket_id,))
        ticket = cursor.fetchone()

        if not ticket:
            print(f"Ticket {ticket_id} non trouvé")
            return None

        comments_cursor = conn.cursor()
        comments_cursor.execute("SELECT text FROM comment WHERE ticket_id = %s", (ticket_id,))
        comments = comments_cursor.fetchall()
        comments_cursor.close()

        def remove_html_tags(text):
            if text is None:
                return ""
            soup = BeautifulSoup(text, "html.parser")
            return soup.get_text(separator=" ", strip=True)

        text_parts = []
        if ticket['summary']:
            text_parts.append(remove_html_tags(ticket['summary']))
        if ticket['description']:
            text_parts.append(remove_html_tags(ticket['description']))
        for comment in comments:
            text_parts.append(remove_html_tags(comment['text']))

        full_text = "\n".join(text_parts)

        if not full_text.strip():
            print(f"Ticket {ticket_id} : texte vide, ignoré")
            return None

        return full_text
    finally:
        cursor.close()
        conn.close()


async def add_ticket_to_chroma(ticket_id: int) -> bool:
    """
    Ajoute ou met à jour un ticket dans la collection Chroma 'tickets'.
    Récupère le ticket et ses commentaires depuis la base de données,
    construit le texte complet, calcule l'embedding et l'ajoute à Chroma.
    """
    try:
        full_text = await asyncio.to_thread(_fetch_ticket_text, ticket_id)
        if full_text is None:
            return False

        col = await tickets_collection()
        ticket_id_str = str(ticket_id)

        # Vérifier si le ticket existe déjà dans Chroma via la métadonnée ticket_id
        existing = await col.get(where={"ticket_id": ticket_id}, include=["documents", "metadatas"])

        if existing.get("ids") and len(existing["ids"]) > 0:
            # Le ticket existe déjà, le mettre à jour
            existing_id = existing["ids"][0]
            await col.update(
                ids=[existing_id],
                documents=[full_text],
                metadatas=[{"ticket_id": ticket_id, "source": "api_add"}]
            )
            print(f"Ticket {ticket_id} mis à jour dans Chroma")
        else:
            # Le ticket n'existe pas, l'ajouter
            await col.add(
                ids=[ticket_id_str],
                documents=[full_text],
                metadatas=[{"ticket_id": ticket_id, "source": "api_add"}]
            )
            print(f"Ticket {ticket_id} ajouté à Chroma")

        print(f"[INFO] {full_text}")
        return True

    except Exception as e:
        print(f"Erreur lors de l'ajout du ticket {ticket_id}: {e}")
        import traceback
        traceback.print_exc()
        return False

async def get_vocabulary_for_term(base_term: str) -> Dict[str, Any]:
    """
    Récupère le vocabulaire (synonymes) pour un terme de base avec ses métadonnées.
    Utilisé pour répondre à des questions comme "Qui a ajouté le terme X ?".

    Returns:
        dict avec les clés:
        - base_term: le terme de base
        - synonyms: liste des synonymes
        - metadata: dict avec username, date, user_id, etc. (ou None si non trouvé)
    """
    col = await memories_collection()

    where = {
        "$and":[
            {"kind": "vocabulary"},
            {"base_term": base_term}
        ]
    }

    res = await col.get(where=where, include=["documents", "metadatas"])
    docs = res.get("documents", [])
    metadatas = res.get("metadatas", [])

    synonyms = []
    metadata = None

    for i, doc in enumerate(docs):
        if doc and doc.strip():
            terms = [t.strip() for t in doc.split(",") if t.strip()]
            synonyms.extend(terms)
            # Prendre les métadonnées du premier document trouvé
            if i < len(metadatas) and metadata is None:
                metadata = metadatas[i]

    print(f"[SYNONYMS] Synonymes trouvés pour '{base_term}': {synonyms}")

    return {
        "base_term": base_term,
        "synonyms": synonyms,
        "metadata": metadata,
        "count": len(synonyms)
    }

async def add_synonyms(base_term: str, synonyms: List[str], user_id: int | None = None, username: str | None = None) -> str:
    """
    Ajoute un ensemble de synonymes pour un terme de base (kind=vocabulary, global).
    """
    # Convertir la liste en chaîne séparée par des virgules
    content = ", ".join(synonyms)

    return await add_memory(
        target_agent="semantic_research",
        kind="vocabulary",
        content=content,
        user_id=user_id,
        base_term=base_term
    )

async def remove_term_from_vocabulary(term: str, base_term: str) -> Dict[str, Any]:
    """
    Supprime une entrée de vocabulaire spécifique.

    Cherche tous les documents de kind=vocabulary avec base_term dans les métadonnées,
    puis supprime l'entrée dont le document est exactement égal au terme à supprimer.
    """
    col = await memories_collection()

    where = {
        "$and":[
            {"kind": "vocabulary"},
            {"base_term": base_term}
        ]
    }

    res = await col.get(where=where, include=["documents"])
    docs = res.get("documents", [])
    ids = res.get("ids", [])

    doc_id_to_delete = None
    for i, doc in enumerate(docs):
        clean_doc = doc.strip().strip('"\'').lower()
        if clean_doc == term.strip().lower():
            doc_id_to_delete = ids[i] if i < len(ids) else None
            break

    if doc_id_to_delete is None:
        return {
            "success": False,
            "message": f"Aucune entrée trouvée avec le document '{term}' pour le terme de base '{base_term}'",
            "base_term": base_term,
            "removed_term": term
        }

    await col.delete(ids=[doc_id_to_delete])

    return {
        "success": True,
        "message": f"L'entrée '{term}' a été supprimée du vocabulaire de '{base_term}'",
        "base_term": base_term,
        "removed_term": term
    }


# ── Gérer les souvenirs ──────────────────────────────────────
_TARGET_AGENT_DEFAULT_SCOPE = {
    "supervisor": "global",         # corrections/exemples de délégation : comportement système
    "sql_research": "global",       # règles de construction SQL : comportement système
    "semantic_research": "user",    # correction de comportement, propre à l'utilisateur
    "conversational": "user",       # préférence de ton/comportement, propre à l'utilisateur
    "memory": "global",             # méta-correction sur la classification : comportement système
}


def _default_scope(target_agent: str, kind: str | None) -> str:
    if kind == "vocabulary":
        return "global"
    return _TARGET_AGENT_DEFAULT_SCOPE.get(target_agent, "user")

def _debug_memory(action: str, header: str, docs: list[str], metas: list[dict] | None = None) -> None:
    """
    Affiche un bloc de débogage pour toute écriture/lecture de souvenir
    """
    print(f"\n{'━' * 64}")
    print(f"[MEMORY {action}] {header}")
    print(f"  → {len(docs)} souvenir(s)")
    for i, doc in enumerate(docs):
        meta = metas[i] if metas and i < len(metas) else None
        print(f"  {i + 1}. {doc}")
        if meta is not None:
            print(f"     meta: {meta}")
    print('━' * 64)


def _memory_where(target_agent: str, user_id: int | None, retrieval: str | None = None, exclude_kind: str | None = None,) -> dict:
    """
    Filtre les souvenirs destinés à ``target_agent`` : ceux de l'utilisateur plus
    ceux de portée globale, éventuellement restreints à un mode de récupération
    (``retrieval`` = "invariant" | "contextual") et/ou excluant un ``kind`` donné.
    Construit un ``$and`` plat.
    """
    conds: list[dict] = [{"target_agent": target_agent}]
    if user_id is not None:
        conds.append({"$or": [{"user_id": user_id}, {"scope": "global"}]})
    if retrieval is not None:
        conds.append({"retrieval": retrieval})
    if exclude_kind is not None:
        conds.append({"kind": {"$ne": exclude_kind}})
    return conds[0] if len(conds) == 1 else {"$and": conds}

def _memory_payload(doc: str, meta: dict | None) -> str:
    """Texte à injecter dans le prompt : la correction (contextuel) ou le
    document lui-même (invariant, où le document EST la règle)."""
    return (meta or {}).get("correction") or doc

async def embed_memory_query(text: str) -> list[float]:
    """Embedding (avec préfixe d'instruction) d'un message pour la recherche de souvenirs."""
    instruction  = (
        "Représente une requête utilisateur pour retrouver des requêtes passées "
        "similaires ayant déclenché une correction."
    )
    return await asyncio.to_thread(get_embedding, f"Instruct: {instruction}\nQuery: {text}")


async def get_memories_text(
    target_agent: str,
    user_id: int | None,
    query: str | None = None,
    query_embedding: list[float] | None = None,
    k: int = 5,
) -> str:
    """
    Renvoie les souvenirs à injecter pour ``target_agent``, en combinant deux voies :

    1. **Invariants** (``retrieval="invariant"``) : règles universelles, TOUJOURS
       injectées (filtre métadonnées, sans similarité).
    2. **Contextuels** (``retrieval="contextual"``) : les ``k`` dont la *requête
       déclencheuse* (le ``document`` embeddé) est la plus proche du message.
       Indexation asymétrique : on compare requête ↔ requête, pas requête ↔ règle.

    ``query_embedding`` : embedding déjà calculé du message (via ``embed_memory_query``),
    pour éviter de ré-embedder le même message d'un agent à l'autre. Sinon il est
    calculé à partir de ``query``. ``query`` reste utilisé pour le log d'accès.

    Le vocabulaire (``kind="vocabulary"``, aussi marqué ``retrieval="invariant"``
    pour la cohérence des métadonnées) est explicitement EXCLU des deux voies : il
    a son propre mécanisme de récupération (``get_vocabulary_for_term`` /
    ``semantic_ticket_search``), pas les blocs de règles injectés ici.
    """
    col = await memories_collection()

    # 1) Invariants — toujours injectés (hors vocabulaire, cf. ci-dessus)
    inv_res = await col.get(
        where=_memory_where(target_agent, user_id, retrieval="invariant", exclude_kind="vocabulary"),
        include=["documents", "metadatas"],
    )
    inv_docs = inv_res.get("documents", []) or []
    inv_metas = inv_res.get("metadatas", []) or []

    # 2) Contextuels — top-k par similarité message ↔ requête déclencheuse
    ctx_docs: list = []
    ctx_metas: list = []
    if query_embedding is None and query:
        query_embedding = await embed_memory_query(query)
    if query_embedding is not None:
        cres = await col.query(
            query_embeddings=[query_embedding],
            n_results=k,
            where=_memory_where(target_agent, user_id, retrieval="contextual"),
            include=["documents", "metadatas"],
        )
        ctx_docs = cres["documents"][0] if cres["documents"] else []
        ctx_metas = cres["metadatas"][0] if cres.get("metadatas") else []

    docs = inv_docs + ctx_docs
    metas = inv_metas + ctx_metas
    # Accès : agent + query ; résultats : contenu + métadonnées de chaque souvenir.
    _debug_memory("ACCESS", f"agent={target_agent} query={query!r}", docs, metas)

    lines = [_memory_payload(d, m) for d, m in zip(docs, metas)]
    return "\n\n---\n\n".join(l for l in lines if l)

async def add_memory(
    target_agent: str,
    content: str,
    user_id: int | None,
    kind: str | None = None,
    retrieval: str | None = None,
    trigger: str | None = None,
    scope: str | None = None,
    embedding: list[float] | None = None,
    base_term: str | None = None,
) -> str:
    """
    Ajoute un souvenir.

    - ``target_agent`` : agent qui devra lire ce souvenir (supervisor,
      sql_research, semantic_research, conversational, memory).
    - ``kind`` : "behavior" (défaut, toute correction de comportement) ou
      "vocabulary" (synonymes — uniquement valide pour ``target_agent="semantic_research"``,
      seul agent doté d'un mécanisme de vocabulaire).
    - ``content`` : le texte de la règle/correction à injecter (le payload).
    - ``retrieval`` : mode de récupération —
        * "invariant"  : règle universelle, toujours injectée. ``document`` = ``content``.
          C'est aussi la valeur par défaut pour le vocabulaire (cohérence des
          métadonnées), même s'il est ensuite exclu de l'injection par
          ``get_memories_text`` (mécanisme dédié).
        * "contextual" : liée à une situation. ``document`` = ``trigger`` (la requête
          déclencheuse, embeddée comme clé), ``content`` conservé en payload ``correction``.
    - ``trigger`` : requête utilisateur déclencheuse (REQUIS si ``retrieval="contextual"``).
    - ``scope`` : "user" ou "global". Si None, déduit de ``target_agent`` (et de ``kind``
      pour le vocabulaire, toujours global) via ``_default_scope``.

    Pour ``kind="vocabulary"`` :
        - content : les termes liés/synonymes (ex: "lent, slow, performance")
        - base_term : le terme de base (ex: "performance") - **REQUIS** - stocké dans les métadonnées
    """
    if kind is None:
        kind = "behavior"
    is_vocab = kind == "vocabulary"

    if scope is None:
        scope = _default_scope(target_agent, kind)
        
    if retrieval is None:
        retrieval = "invariant"
        
    username = await asyncio.to_thread(get_username, user_id)
    meta = {
        "target_agent": target_agent,
        "kind": kind,
        "scope": scope,
        "user_id": user_id if user_id is not None else -1,
        "username": username or "",
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    if retrieval is not None:
        meta["retrieval"] = retrieval

    # Pour le vocabulaire, ajouter le terme de base dans les métadonnées
    if is_vocab:
        meta["base_term"] = base_term

    # Indexation asymétrique : pour un souvenir contextuel, la clé de recherche
    # (document embeddé) est la requête déclencheuse ; la règle reste en payload.
    if retrieval == "contextual":
        document = trigger or content
        meta["correction"] = content
    else:
        document = content

    doc_id = str(uuid.uuid4())
    kwargs = {"ids": [doc_id], "documents": [document], "metadatas": [meta]}
    if embedding is not None:
        kwargs["embeddings"] = [embedding]
    col = await memories_collection()
    await col.add(**kwargs)
    _debug_memory("STORE", f"id={doc_id}", [document], [meta])
    return doc_id

async def delete_memory(memory_id: str) -> bool:
    """
    Supprime un souvenir par son ID.
    """
    col = await memories_collection()
    await col.delete(ids=[memory_id])
    return True

async def update_memory(
    memory_id: str,
    target_agent: str | None = None,
    content: str | None = None,
    user_id: int | None = None,
    kind: str | None = None,
    retrieval: str | None = None,
    trigger: str | None = None,
    scope: str | None = None,
    embedding: list[float] | None = None,
    base_term: str | None = None,
) -> bool:
    """
    Met à jour un souvenir existant
    """
    col = await memories_collection()

    res = await col.get(ids=[memory_id], include=["documents", "metadatas"])
    if not res["ids"] or len(res["ids"]) == 0:
        return False

    existing_doc = res["documents"][0] if res["documents"] and len(res["documents"]) > 0 else ""
    existing_meta = res["metadatas"][0] if res["metadatas"] and len(res["metadatas"]) > 0 else {}
    if not isinstance(existing_meta, dict):
        existing_meta = {}

    if kind is None:
        kind = existing_meta.get("kind", "behavior")
    is_vocab = kind == "vocabulary"

    if scope is None:
        scope = existing_meta.get("scope") or _default_scope(target_agent or existing_meta.get("target_agent", ""), kind)

    if retrieval is None:
        retrieval = existing_meta.get("retrieval", "invariant")

    if user_id is None:
        user_id = existing_meta.get("user_id")

    if target_agent is None:
        target_agent = existing_meta.get("target_agent")

    username = existing_meta.get("username")
    if user_id is not None:
        username = await asyncio.to_thread(get_username, user_id)

    meta = {
        "target_agent": target_agent,
        "kind": kind,
        "scope": scope,
        "user_id": user_id if user_id is not None else -1,
        "username": username or "",
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    if retrieval is not None:
        meta["retrieval"] = retrieval

    if is_vocab:
        if base_term is not None:
            meta["base_term"] = base_term
        elif "base_term" in existing_meta:
            meta["base_term"] = existing_meta["base_term"]

    if retrieval == "contextual":
        document = trigger or content or existing_doc
        meta["correction"] = content or existing_meta.get("correction", "")
    else:
        document = content or existing_doc

    kwargs = {"ids": [memory_id], "metadatas": [meta]}
    if embedding is not None:
        kwargs["embeddings"] = [embedding]
    if retrieval != "contextual" or trigger is not None or content is None:
        kwargs["documents"] = [document]

    await col.update(**kwargs)
    _debug_memory("UPDATE", f"id={memory_id}", [document], [meta])
    return True

async def get_all_memories() -> dict:
    """
    Récupère tous les souvenirs de la collection ``memories``, sous une forme
    **normalisée** pour l'affichage (frontend) : le ``document`` ambigu est
    résolu en champs explicites selon la structure du souvenir.

    Chaque souvenir a TOUJOURS les mêmes clés (``null`` si non applicable) :
    - identité/classification : ``id``, ``target_agent``, ``kind``, ``retrieval``,
      ``scope``, ``user_id``, ``username``, ``date``.
    - contenu selon la forme :
        * contextuel : ``trigger`` (la requête déclencheuse) + ``rule`` (la règle injectée).
        * invariant  : ``rule`` (le document EST la règle), ``trigger`` = null.
        * vocabulaire: ``base_term`` + ``synonyms`` (le document), ``rule``/``trigger`` = null.
    """
    col = await memories_collection()
    res = await col.get(include=["documents", "metadatas"])
    memories = []
    for i, doc_id in enumerate(res['ids']):
        meta = res['metadatas'][i] or {}
        document = res['documents'][i]
        kind = meta.get('kind')
        retrieval = meta.get('retrieval')

        trigger = rule = base_term = synonyms = None
        if kind == "vocabulary":
            base_term = meta.get('base_term')
            synonyms = document
        elif retrieval == "contextual":
            trigger = document
            rule = meta.get('correction')
        else:  # invariant (ou legacy sans retrieval) : le document est la règle
            rule = document

        memories.append({
            "id": doc_id,
            "target_agent": meta.get('target_agent'),
            "kind": kind,
            "retrieval": retrieval,
            "scope": meta.get('scope'),
            "user_id": meta.get('user_id'),
            "username": meta.get('username'),
            "date": meta.get('date'),
            "trigger": trigger,
            "rule": rule,
            "base_term": base_term,
            "synonyms": synonyms,
        })

    return {'memories': memories}

async def get_last_memory(user_id: int | None) -> dict | None:
    """
    Récupère le dernier souvenir (tous types confondus) créé par l'utilisateur.
    Retourne None si aucun souvenir.
    """
    col = await memories_collection()
    where = {"user_id": user_id}
    res = await col.get(where=where, include=["documents", "metadatas"])

    if not res.get("ids") or len(res["ids"]) == 0:
        return ''

    ids = res["ids"]
    docs = res["documents"]
    metas = res["metadatas"]
    last_index = 0
    last_date = ""

    for i, meta in enumerate(metas):
        if isinstance(meta, dict) and "date" in meta:
            if meta["date"] > last_date:
                last_date = meta["date"]
                last_index = i

    return {
        "id": ids[last_index],
        "content": docs[last_index],
        "metadata": metas[last_index]
    }

# ── Résumés de conversation ─────────────────────────────────────────────────

async def add_conversation_summary(user_id: int, conversation_id: int, summary: str, embedding: list[float] | None = None) -> str:
    """
    Enregistre un résumé de conversation (rappel de contexte inter-sessions).
    """
    meta = {
        "user_id": user_id,
        "conversation_id": conversation_id,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    doc_id = str(uuid.uuid4())
    kwargs = {"ids": [doc_id], "documents": [summary], "metadatas": [meta]}
    if embedding is not None:
        kwargs["embeddings"] = [embedding]
    col = await summaries_collection()
    await col.add(**kwargs)
    return doc_id

async def search_conversation_summaries(user_id: int, query: str, k: int = 3) -> str:
    """
    Renvoie les ``k`` résumés de conversation les plus pertinents pour l'utilisateur.
    Utilise un embedding avec préfixe d'instruction pour améliorer la recherche.
    """
    col = await summaries_collection()
    if await col.count() == 0:
        return ""

    # Préfixe pour la recherche de résumés de conversation
    summary_instruction = (
        "Représente une requête pour retrouver des résumés de conversation pertinents. "
        "Inclut le contexte conversationnel, les thèmes abordés et les concepts associés."
    )

    query_embedding = await asyncio.to_thread(get_embedding, f"Instruct: {summary_instruction}\nQuery: {query}")
    res = await col.query(
        query_embeddings=[query_embedding], n_results=k, where={"user_id": user_id}, include=["documents"]
    )
    docs = res["documents"][0] if res["documents"] else []
    return "\n\n---\n\n".join(docs)
