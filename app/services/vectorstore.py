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
DEFAULT_THRESHOLD = 0.5

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
    """
    emb_fn = get_embedding_function()
    embeddings = emb_fn([text])
    return embeddings[0]


def get_query_embedding(query: str, instruction_prefix: str = None) -> list[float]:
    """
    Calcule l'embedding d'une requête avec un préfixe d'instruction.

    """
    if instruction_prefix is None:
        instruction_prefix = (
            "Trouve les tickets pertinents pour une demande donnée en identifiant ceux qui mentionnent, décrivent ou traitent du sujet spécifié. "
            "Inclus les tickets qui contiennent des termes directement liés ou des concepts sémantiquement proches."
        )
    
    full_text = f"{instruction_prefix}\n\n{query}"
    return get_embedding(full_text)


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

def query_tickets(query: list[float] | str, nb_results: int = 10) -> list[int]:
    """
    Renvoie les {nb_results} ``ticket_id`` les plus similaires à {query}.
    """
    col = tickets_collection()
    
    if isinstance(query, str):
        query_embedding = get_query_embedding(query)
    else:
        query_embedding = query
    
    res = col.query(
        query_embeddings=[query_embedding],
        n_results=nb_results,
        include=["distances"],
    )
    
    ids = res["ids"][0]
    
    # Convertir en int (les ticket_ids sont stockés comme strings dans Chroma)
    return [int(tid) for tid in ids]


def query_tickets_with_synonyms(query: str, nb_results_per_synonym: int = 10, final_nb_results: int = 10) -> list[int]:
    """
    Recherche des tickets en tenant compte des synonymes expand_vocabulary.
    
    Pour chaque synonyme trouvé pour le terme de base, fait une requête séparée
    avec un embedding calculé sur "cherche les tickets qui parlent de: <synonyme>".
    Fusionne tous les résultats, les trie par score, et retourne les N meilleurs.
    """

    synonyms = get_synonyms_for_term(query)

    if not synonyms:
        return query_tickets(query, nb_results=final_nb_results)
    
    all_terms = [query] + synonyms
    
    query_instruction = (
        "Trouve les tickets pertinents pour une demande donnée en identifiant ceux qui mentionnent, décrivent ou traitent du sujet spécifié. "
        "Inclus les tickets qui contiennent des termes directement liés ou des concepts sémantiquement proches."
        "Cherche les tickets qui parlent de: "
    )
    
    all_embeddings = []
    for term in all_terms:
        embedding = get_embedding(f"{query_instruction}{term}")
        all_embeddings.append(embedding)
    
    col = tickets_collection()
    res = col.query(
        query_embeddings=all_embeddings,
        n_results=nb_results_per_synonym,
        include=["distances"]
    )
    
    # Fusionner tous les résultats, les trier par distance et retoruner les n meilleurs
    all_results = []
    for i in range(len(all_embeddings)):
        ids = res["ids"][i]
        distances = res["distances"][i]
        for j in range(len(ids)):
            all_results.append({
                "id": int(ids[j]),
                "distance": distances[j],
                "term_index": i
            })

    all_results.sort(key=lambda x: x["distance"])
    
    return [r["id"] for r in all_results[:final_nb_results]]


# ── Mémoires (souvenirs / corrections) ──────────────────────────────────────

def _memory_where(type: str, user_id: int | None) -> dict:
    # expand_vocabulary est global (partagé) ; les autres types sont par utilisateur.
    if type == "expand_vocabulary" or user_id is None:
        return {"type": type}
    return {"$and": [{"type": type}, {"$or": [{"user_id": user_id}, {"scope": "global"}]}]}


def get_synonyms_for_term(base_term: str) -> List[str]:
    """
    Récupère tous les termes liés/synonymes pour un terme de base donné.
    Utilise le filtre where sur les métadonnées pour une recherche exacte.
    """
    col = memories_collection()

    where = {
        "$and":[
            {"type": "expand_vocabulary"},
            {"base_term": base_term}
        ]
    }
    
    res = col.get(where=where, include=["documents", "metadatas"])
    docs = res.get("documents", [])
    
    synonyms = []
    for doc in docs:
        if doc and doc.strip():
            terms = [t.strip() for t in doc.split(",") if t.strip()]
            synonyms.extend(terms)
    
    print(f"[SYNONYMS] Synonymes trouvés pour '{base_term}': {synonyms}")
    
    return synonyms

def get_memories_text(type: str, user_id: int | None, query: str | None = None, k: int = 8) -> str:
    """
    Renvoie les souvenirs d'un ``type`` sous forme de texte concaténé.

    - Sans ``query`` : tous les souvenirs du type (filtrés par métadonnées).
    - Avec ``query`` : les ``k`` souvenirs les plus proches sémantiquement (avec préfixe d'instruction).
    Vide si aucun souvenir
    """
    col = memories_collection()
    where = _memory_where(type, user_id)
    if query:
        # Calculer l'embedding avec préfixe pour les mémoires
        memory_instruction = (
            "Représente une question ou un contexte pour retrouver des souvenirs ou corrections pertinents. "
            "Inclut les synonymes, concepts liés et variations sémantiques."
        )
        query_embedding = get_query_embedding(query, instruction_prefix=memory_instruction)
        res = col.query(query_embeddings=[query_embedding], n_results=k, where=where, include=["documents"])
        docs = res["documents"][0] if res["documents"] else []
    else:
        res = col.get(where=where, include=["documents"])
        docs = res.get("documents", []) or []
    return "\n\n---\n\n".join(docs)


def add_synonyms(base_term: str, synonyms: List[str], user_id: int | None = None, username: str | None = None) -> str:
    """
    Ajoute un ensemble de synonymes pour un terme de base (type expand_vocabulary).
    
    Args:
        base_term: Le terme de base (ex: "performance")
        synonyms: Liste des termes liés/synonymes (ex: ["lent", "slow", "rapide"])
        user_id: ID de l'utilisateur (optionnel, car expand_vocabulary est global)
        username: Nom de l'utilisateur
    
    Returns:
        L'ID du document ajouté
    """
    # Convertir la liste en chaîne séparée par des virgules
    content = ", ".join(synonyms)
    
    return add_memory(
        type="expand_vocabulary",
        content=content,
        user_id=user_id,
        username=username,
        base_term=base_term
    )


def add_memory(type: str, content: str, user_id: int | None, username: str | None = None, embedding: list[float] | None = None, base_term: str | None = None) -> str:
    """
    Ajoute un souvenir.
    
    Pour le type 'expand_vocabulary' :
        - content : les termes liés/synonymes (ex: "lent, slow, performance")
        - base_term : le terme de base (ex: "performance") - **REQUIS** - stocké dans les métadonnées
    Pour les autres types :
        - content : le souvenir/correction
        - base_term : non utilisé
    """
    scope = "global" if type == "expand_vocabulary" else "user"
    meta = {
        "type": type,
        "scope": scope,
        "user_id": user_id if user_id is not None else -1,
        "username": username or "",
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    
    # Pour expand_vocabulary, ajouter le terme de base dans les métadonnées
    if type == "expand_vocabulary":
        if not base_term:
            # Essayer d'extraire base_term du content si format "base: syn1, syn2"
            if ":" in content:
                base_term = content.split(":")[0].strip()
                print(f"[WARNING] base_term extrait du content: '{base_term}'")
            else:
                raise ValueError(
                    f"Pour type='expand_vocabulary', base_term est requis. "
                    f"Content: '{content}'"
                )
        meta["base_term"] = base_term
    
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
    Utilise un embedding avec préfixe d'instruction pour améliorer la recherche.
    """
    col = summaries_collection()
    if col.count() == 0:
        return ""
    
    # Préfixe pour la recherche de résumés de conversation
    summary_instruction = (
        "Représente une requête pour retrouver des résumés de conversation pertinents. "
        "Inclut le contexte conversationnel, les thèmes abordés et les concepts associés."
    )
    query_embedding = get_query_embedding(query, instruction_prefix=summary_instruction)
    
    res = col.query(
        query_embeddings=[query_embedding], n_results=k, where={"user_id": user_id}, include=["documents"]
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
    Utilise un embedding avec préfixe d'instruction pour améliorer la recherche.
    """
    col = supervisor_actions_collection()
    if col.count() == 0:
        return []
    
    # Préfixe spécifique pour la recherche d'exemples de supervision
    supervisor_instruction = (
        "Représente une requête utilisateur pour déterminer l'action appropriée à entreprendre. "
        "Analyse la sémantique, l'intention et le contexte pour identifier des exemples similaires "
        "qui aideront à prendre la bonne décision de délégation."
    )
    query_embedding = get_query_embedding(query, instruction_prefix=supervisor_instruction)
    
    res = col.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        include=["documents", "metadatas", "distances"]
    )
    
    results = []
    ids = res.get("ids", [[ ]])[0]
    documents = res.get("documents", [[ ]])[0]
    metadatas = res.get("metadatas", [[ ]])[0]
    distances = res.get("distances", [[ ]])[0]
    
    for i in range(len(ids)):
        results.append({
            "id": ids[i],
            "user_query": documents[i],
            "metadata": metadatas[i] if i < len(metadatas) else {},
            "distance": distances[i] if i < len(distances) else None
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

# Update / Delete memories

def get_last_memory(user_id: int | None) -> dict | None:
    """
    Récupère le dernier souvenir (tous types confondus) créé par l'utilisateur.
    Retourne None si aucun souvenir.
    """
    col = memories_collection()
    where = {"user_id": user_id}
    res = col.get(where=where, include=["documents", "metadatas"])

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

def delete_memory(memory_id: str, user_id: int | None) -> bool:
    """
    Supprime un souvenir par son ID.
    """
    col = memories_collection()
    col.delete(ids=[memory_id])
    return True


def update_memory(memory_id: str, new_content: str, user_id: int | None, username: str | None = None) -> bool:
    """
    Met à jour un souvenir existant.
    """
    col = memories_collection()
    # Conserver les métadonnées existantes
    res = col.get(ids=[memory_id], include=["metadatas"])
    if not res["ids"] or len(res["ids"]) == 0:
        return False
    
    existing_meta = res["metadatas"][0] if res["metadatas"] and len(res["metadatas"]) > 0 else {}
    if isinstance(existing_meta, dict):
        # Mettre à jour la date
        existing_meta["date"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # Mettre à jour username si fourni
        if username:
            existing_meta["username"] = username
    else:
        existing_meta = {}
    
    col.update(
        ids=[memory_id],
        documents=[new_content],
        metadatas=[existing_meta]
    )
    return True