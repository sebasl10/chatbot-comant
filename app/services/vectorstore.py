"""
Base vectorielle Chroma — tickets, mémoires, résumés de conversation.

Remplace le duo (table MySQL ``ticket_embedding`` + cosine en Python) et le
stockage Markdown des souvenirs, par un client Chroma persistant unique.

Collections :
- ``tickets``                : embeddings de tickets.
- ``memories``               : souvenirs/corrections + exemples de routage, filtrables par métadonnées ``{target_agent, kind, scope, user_id}`` et recherchables sémantiquement. Guide aussi le superviseur (``target_agent=supervisor``).
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
        "ef_construction": 200,
        "ef_search": 200
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

# ── Recherche sémantique de tickets ─────────────────────────────────────────

async def query_tickets(query: list[float] | str, threshold: float = 0.55, use_synonyms: bool = True) -> dict:
    """
    Recherche des tickets sémantiquement proches de la query.
    Récupère toujours 3000 résultats puis filtre ceux avec distance <= threshold.
    """
    col = await tickets_collection()

    """ query_instruction = (
        "Trouve les tickets pertinents pour une demande donnée en identifiant ceux qui mentionnent, décrivent ou traitent du sujet spécifié. "
        "Inclus les tickets qui contiennent des termes directement liés ou des concepts sémantiquement proches."
        "Donne la priorité aux tickets qui contiennent exactement le sujet."
    ) """
    #query_instruction = "Given a search query, retrieve support tickets that discuss the specified topic or technical concept."
    query_instruction = "Given a technical term or topic, retrieve customer support tickets that mention or relate to it, even briefly."

    all_embeddings = []
    terms_used = []


    if use_synonyms:
        synonyms = (await get_vocabulary_for_term(query))["synonyms"]
        if synonyms:
            all_terms = [query] + synonyms
            prompts = [f"Instruct: {query_instruction}\nQuery: {term}" for term in all_terms]
            all_embeddings = await get_embeddings(prompts)
            terms_used = all_terms

    if not all_embeddings:
        all_embeddings = await get_embeddings([f"Instruct: {query_instruction}\nQuery: {query}"])
        terms_used = [query]

    res = await col.query(
        query_embeddings=all_embeddings,
        n_results=3000,
        include=["distances"]
    )

    all_results = []
    for i in range(len(all_embeddings)):
        ids = res["ids"][i]
        distances = res["distances"][i]
        for j in range(len(ids)):
            all_results.append({
                "id": int(ids[j]),
                "distance": distances[j],
            })

    all_results.sort(key=lambda x: x["distance"])
    filtered_results = [r for r in all_results if r["distance"] <= threshold]
    ticket_ids = [r["id"] for r in filtered_results]

    return {
        "ticket_ids": ticket_ids,
        "synonyms": terms_used,
        "count": len(ticket_ids)
    }

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
    _debug_memory("RETRIEVE VOCAB", f"base_term={base_term!r} where={where}", docs, metadatas)

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

# Portée par défaut selon la nature (kind) du souvenir, quand ``scope`` n'est pas
# fourni explicitement. Les règles « système » (comportement partagé par tous les
# utilisateurs) sont globales ; ce qui est propre à un utilisateur reste local.
_KIND_DEFAULT_SCOPE = {
    "sql_rule": "global",     # règles de construction SQL : comportement système
    "routing": "global",      # corrections/exemples de délégation : comportement système
    "vocabulary": "global",   # synonymes partagés
    "exclude": "user",        # exclusion de ticket : plutôt une préférence de filtrage
    "other": "user",          # non classé : local par prudence
}

def _debug_memory(action: str, header: str, docs: list[str], metas: list[dict] | None = None) -> None:
    """
    Affiche un bloc de débogage pour toute écriture/lecture de souvenir :
    contenu + métadonnées, pour vérifier quand et quoi est stocké/récupéré.

    ``action`` : "STORE" | "RETRIEVE" | "RETRIEVE VOCAB" ...
    ``header`` : contexte (target_agent, query, where, id…).
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


def _memory_where(target_agent: str, user_id: int | None) -> dict:
    """
    Filtre les souvenirs destinés à ``target_agent`` : ceux de l'utilisateur
    plus ceux de portée globale. Si ``user_id`` est None, ne filtre que par agent.
    """
    if user_id is None:
        return {"target_agent": target_agent}
    return {"$and": [{"target_agent": target_agent}, {"$or": [{"user_id": user_id}, {"scope": "global"}]}]}

async def get_memories_text(target_agent: str, user_id: int | None, query: str | None = None, k: int = 6) -> str:
    """
    Renvoie les souvenirs destinés à ``target_agent`` sous forme de texte concaténé.

    - Avec ``query`` (cas normal) : les ``k`` souvenirs les plus proches
      sémantiquement de la requête condensée (préfixe d'instruction).
    - Sans ``query`` (fallback) : tous les souvenirs de l'agent (filtrés par métadonnées).
    Vide si aucun souvenir.
    """
    col = await memories_collection()
    where = _memory_where(target_agent, user_id)
    if query:
        # Calculer l'embedding avec préfixe pour les mémoires
        memory_instruction = (
            "Représente une question ou un contexte pour retrouver des souvenirs ou corrections pertinents. "
            "Inclut les synonymes, concepts liés et variations sémantiques."
        )
        query_embedding = await asyncio.to_thread(get_embedding, f"Instruct: {memory_instruction}\nQuery: {query}")
        res = await col.query(query_embeddings=[query_embedding], n_results=k, where=where, include=["documents", "metadatas"])
        docs = res["documents"][0] if res["documents"] else []
        metas = res["metadatas"][0] if res.get("metadatas") else []
    else:
        res = await col.get(where=where, include=["documents", "metadatas"])
        docs = res.get("documents", []) or []
        metas = res.get("metadatas", []) or []
    _debug_memory("RETRIEVE", f"target_agent={target_agent} user_id={user_id} k={k} query={query!r} where={where}", docs, metas)
    return "\n\n---\n\n".join(docs)

async def add_memory(
    target_agent: str,
    kind: str,
    content: str,
    user_id: int | None,
    scope: str | None = None,
    embedding: list[float] | None = None,
    base_term: str | None = None,
) -> str:
    """
    Ajoute un souvenir.

    - ``target_agent`` : agent qui devra lire ce souvenir (supervisor,
      sql_research, semantic_research, conversational).
    - ``kind`` : nature du souvenir (sql_rule, exclude, vocabulary, routing, other).
    - ``scope`` : "user" ou "global" (partagé entre utilisateurs). Si None, la
      portée est déduite du ``kind`` via ``_KIND_DEFAULT_SCOPE``
      (sql_rule/routing/vocabulary → global ; exclude/other → user).

    Pour ``kind == "vocabulary"`` :
        - content : les termes liés/synonymes (ex: "lent, slow, performance")
        - base_term : le terme de base (ex: "performance") - **REQUIS** - stocké dans les métadonnées
    Pour les autres kinds :
        - content : le souvenir/correction
        - base_term : non utilisé
    """
    if scope is None:
        scope = _KIND_DEFAULT_SCOPE.get(kind, "user")
    username = await asyncio.to_thread(get_username, user_id)
    meta = {
        "target_agent": target_agent,
        "kind": kind,
        "scope": scope,
        "user_id": user_id if user_id is not None else -1,
        "username": username or "",
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    # Pour le vocabulaire, ajouter le terme de base dans les métadonnées
    if kind == "vocabulary":
        meta["base_term"] = base_term

    doc_id = str(uuid.uuid4())
    kwargs = {"ids": [doc_id], "documents": [content], "metadatas": [meta]}
    if embedding is not None:
        kwargs["embeddings"] = [embedding]
    col = await memories_collection()
    await col.add(**kwargs)
    _debug_memory("STORE", f"id={doc_id}", [content], [meta])
    return doc_id

async def delete_memory(memory_id: str) -> bool:
    """
    Supprime un souvenir par son ID.
    """
    col = await memories_collection()
    await col.delete(ids=[memory_id])
    return True


async def update_memory(memory_id: str, new_content: str, username: str | None = None) -> bool:
    """
    Met à jour un souvenir existant.
    """
    col = await memories_collection()

    res = await col.get(ids=[memory_id], include=["metadatas"])
    if not res["ids"] or len(res["ids"]) == 0:
        return False

    existing_meta = res["metadatas"][0] if res["metadatas"] and len(res["metadatas"]) > 0 else {}
    if isinstance(existing_meta, dict):
        existing_meta["date"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if username:
            existing_meta["username"] = username
    else:
        existing_meta = {}

    await col.update(
        ids=[memory_id],
        documents=[new_content],
        metadatas=[existing_meta]
    )
    return True

async def get_all_memories() -> dict:
    """
    Recupère tous les souvenirs de la collection memories
    """
    col = await memories_collection()
    res = await col.get(include=["documents", "metadatas"])
    memories = []
    for i, doc_id in enumerate(res['ids']):
        meta = res['metadatas'][i] or {}
        memory = {
            "text": res['documents'][i],
            "id": doc_id,
            "user_id": meta.get('user_id'),
            "date": meta.get('date'),
            "target_agent": meta.get('target_agent'),
            "kind": meta.get('kind'),
            "scope": meta.get('scope'),
            "username": meta.get('username'),
        }

        if meta.get('base_term'):
            memory["base_term"] = meta['base_term']

        memories.append(memory)

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
