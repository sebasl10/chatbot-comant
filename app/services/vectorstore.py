"""Base vectorielle Chroma — tickets, mémoires, résumés de conversation.

Remplace le duo (table MySQL ``ticket_embedding`` + cosine en Python) et le
stockage Markdown des souvenirs, par un client Chroma persistant unique.

Collections :
- ``tickets``                : embeddings de tickets.
- ``memories``               : souvenirs/corrections, filtrables par métadonnées ``{type, scope, user_id}`` et recherchables sémantiquement.
- ``conversation_summaries`` : résumés de conversation.
- ``supervisor_actions``     : exemples de requêtes utilisateur et actions correspondantes pour l'agent supervisor.
"""

from __future__ import annotations
from typing import Any, Dict, List
import requests
from chromadb import HttpClient
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
import uuid
from datetime import datetime
from app.config import settings

TICKETS = "tickets"
MEMORIES = "memories"
CONVERSATION_SUMMARIES = "conversation_summaries"
SUPERVISOR_ACTIONS = "supervisor_actions"
DEFAULT_HNSW_CONFIG = {
    "space": "cosine",
    "ef_construction": 1000,
    "ef_search": 1000
}

class OllamaEmbeddingFunction(EmbeddingFunction):
    """
    Embeddings via l'endpoint /api/embed d'Ollama (même modèle que les tickets).
    """

    def __init__(self, url: str | None = None, model: str | None = None):
        self._url = url or settings.ollama_url_embedding
        self._model = model or settings.model_ia_embedding

    def __call__(self, input: Documents) -> Embeddings:
        resp = requests.post(self._url, json={"model": self._model, "input": list(input)})
        resp.raise_for_status()
        return resp.json()["embeddings"]

    @staticmethod
    def name() -> str:
        return "ollama_embed"


_client: HttpClient | None = None

def get_client() -> HttpClient:
    global _client
    if _client is None:
        _client = HttpClient(host=settings.chroma_http_url)
    return _client


def _collection(name: str):
    return get_client().get_or_create_collection(
        name, metadata=DEFAULT_HNSW_CONFIG, embedding_function=OllamaEmbeddingFunction()
    )


def tickets_collection():
    return _collection(TICKETS)


def memories_collection():
    return _collection(MEMORIES)


def summaries_collection():
    return _collection(CONVERSATION_SUMMARIES)


def supervisor_actions_collection():
    return _collection(SUPERVISOR_ACTIONS)


# ── Recherche sémantique de tickets ─────────────────────────────────────────

def query_tickets(query_embedding: list[float], threshold: float = 0.5) -> list[int]:
    """
    Renvoie les ``ticket_id`` dont la similarité cosinus >= ``threshold``,
    triés par pertinence décroissante. ``query_embedding`` est déjà calculé par
    l'appelant (avec le préfixe d'instruction), pour la parité avec l'ancien code.
    """
    col = tickets_collection()
    n = col.count()
    if n == 0:
        return []
    res = col.query(
        query_embeddings=[query_embedding],
        n_results=n,
        include=["distances"],
    )
    ids = res["ids"][0]
    distances = res["distances"][0]
    max_distance = 1.0 - threshold
    out: list[int] = []
    for tid, dist in zip(ids, distances):
        if dist <= max_distance:
            out.append(int(tid))
    return out


# ── Mémoires (souvenirs / corrections) ──────────────────────────────────────

def _memory_where(type: str, user_id: int | None) -> dict:
    # expand_vocabulary est global (partagé) ; les autres types sont par utilisateur.
    if type == "expand_vocabulary" or user_id is None:
        return {"type": type}
    return {"$and": [{"type": type}, {"$or": [{"user_id": user_id}, {"scope": "global"}]}]}


def get_memories_text(type: str, user_id: int | None, query: str | None = None, k: int = 8) -> str:
    """
    Renvoie les souvenirs d'un ``type`` sous forme de texte concaténé.

    - Sans ``query`` : tous les souvenirs du type (filtrés par métadonnées).
    - Avec ``query`` : les ``k`` souvenirs les plus proches sémantiquement.
    Vide si aucun souvenir
    """
    col = memories_collection()
    where = _memory_where(type, user_id)
    if query:
        res = col.query(query_texts=[query], n_results=k, where=where, include=["documents"])
        docs = res["documents"][0] if res["documents"] else []
    else:
        res = col.get(where=where, include=["documents"])
        docs = res.get("documents", []) or []
    return "\n\n---\n\n".join(docs)


def add_memory(type: str, content: str, user_id: int | None, username: str | None = None, embedding: list[float] | None = None) -> str:
    """
    Ajoute un souvenir.
    """
    scope = "global" if type == "expand_vocabulary" else "user"
    meta = {
        "type": type,
        "scope": scope,
        "user_id": user_id if user_id is not None else -1,
        "username": username or "",
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    doc_id = str(uuid.uuid4())
    kwargs = {"ids": [doc_id], "documents": [content], "metadatas": [meta]}
    if embedding is not None:
        kwargs["embeddings"] = [embedding]
    memories_collection().add(**kwargs)
    return doc_id


# ── Résumés de conversation ─────────────────────────────────────────────────

def add_conversation_summary(user_id: int, conversation_id: int, summary: str, embedding: list[float] | None = None) -> str:
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
    summaries_collection().add(**kwargs)
    return doc_id

def search_conversation_summaries(user_id: int, query: str, k: int = 3) -> str:
    """
    Renvoie les ``k`` résumés de conversation les plus pertinents pour l'utilisateur.
    """
    col = summaries_collection()
    if col.count() == 0:
        return ""
    res = col.query(
        query_texts=[query], n_results=k, where={"user_id": user_id}, include=["documents"]
    )
    docs = res["documents"][0] if res["documents"] else []
    return "\n\n---\n\n".join(docs)


# ── Exemples de supervision ─────────────────────────────────────────────────

def add_supervisor_example(user_query: str, action: str, description: str = "") -> str:
    """
    Ajoute un exemple de requête utilisateur et l'action correspondante pour l'agent supervisor.
    
    Args:
        user_query: La requête de l'utilisateur (sera le document)
        action: L'action à entreprendre (ex: delegate_new_research, delegate_semantic_search)
        description: Description optionnelle de l'exemple
    
    Returns:
        L'ID du document ajouté
    """
    meta = {
        "action": action,
        "type": "supervisor_example",
        "description": description,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    doc_id = str(uuid.uuid4())
    supervisor_actions_collection().add(
        ids=[doc_id],
        documents=[user_query],
        metadatas=[meta]
    )
    return doc_id


def get_supervisor_examples(query: str, n_results: int = 5) -> List[Dict[str, Any]]:
    """
    Recherche des exemples de supervision similaires à une requête utilisateur.
    
    Args:
        query: La requête de l'utilisateur
        n_results: Nombre maximum d'exemples à retourner
    
    Returns:
        Liste de dictionnaires avec id, document (user_query), metadata (action, etc.)
    """
    col = supervisor_actions_collection()
    if col.count() == 0:
        return []
    
    res = col.query(
        query_texts=[query],
        n_results=n_results,
        include=["documents", "metadatas"]
    )
    
    results = []
    ids = res.get("ids", [[ ]])[0]
    documents = res.get("documents", [[ ]])[0]
    metadatas = res.get("metadatas", [[ ]])[0]
    
    for i in range(len(ids)):
        results.append({
            "id": ids[i],
            "user_query": documents[i],
            "metadata": metadatas[i] if i < len(metadatas) else {},
            "distance": res.get("distances", [[ ]])[0][i] if res.get("distances") else None
        })
    
    return results


def get_all_supervisor_examples() -> List[Dict[str, Any]]:
    """
    Récupère tous les exemples de supervision.
    
    Returns:
        Liste complète des exemples avec leurs métadonnées
    """
    col = supervisor_actions_collection()
    res = col.get(include=["documents", "metadatas"])
    
    results = []
    ids = res.get("ids", [])
    documents = res.get("documents", [])
    metadatas = res.get("metadatas", [])
    
    for i in range(len(ids)):
        results.append({
            "id": ids[i],
            "user_query": documents[i],
            "metadata": metadatas[i] if i < len(metadatas) else {}
        })
    
    return results
