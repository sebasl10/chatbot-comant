import uuid
import requests
from datetime import datetime
from typing import Dict, Any, List, Optional, Union
from chromadb import Documents, EmbeddingFunction, Embeddings, HttpClient, Collection
from chromadb.utils.embedding_functions import register_embedding_function
from app.config import settings

# Configuration HNSW par défaut pour les collections
DEFAULT_HNSW_CONFIG = {
    "space": "cosine",
    "ef_construction": 1000,
    "ef_search": 1000
}

@register_embedding_function
class ChromaEmbeddingFunction(EmbeddingFunction):
    """
    Fonction d'embedding personnalisée pour Chroma qui utilise Ollama.
    """
    
    def __init__(self, model: str = None):
        self.model = model or settings.model_ia_embedding

    def __call__(self, input: List[str]) -> Embeddings:
        texts = input if isinstance(input, list) else [input]
        response = requests.post(
            settings.ollama_url_embedding, 
            json={"model": self.model, "input": texts}
        )
        response.raise_for_status()
        embeddings = response.json()["embeddings"]
        return embeddings

    @staticmethod
    def name() -> str:
        return "ollama_embed"

    def get_config(self) -> Dict[str, Any]:
        return {"model": self.model}

    @staticmethod
    def build_from_config(config: Dict[str, Any]) -> "EmbeddingFunction":
        return ChromaEmbeddingFunction(config.get('model', settings.model_ia_embedding))

class ChromaService:
    """
    Service pour gérer les mémoires avec ChromaDB.
    
    Ce service permet de:
    - Créer et gérer plusieurs collections de mémoires
    - Ajouter des mémoires avec métadonnées dans n'importe quelle collection
    - Récupérer des mémoires par ID ou par requête
    - Supprimer des mémoires
    - Rechercher des mémoires similaires
    """
    
    def __init__(self, host: str = 'localhost', port: int = 8000, default_collection_name: str = "memories", embedding_model: str = None):
        """
        Initialise le service Chroma.
        """
        self.host = host
        self.port = port
        self.default_collection_name = default_collection_name
        self.embedding_model = embedding_model or settings.model_ia_embedding
        self.client = HttpClient(host=self.host, port=self.port)
        self._collections_cache: Dict[str, Collection] = {}
        
        self._get_or_create_collection(default_collection_name)
    
    def _create_embedding_function(self, model: str = None) -> ChromaEmbeddingFunction:
        """Crée une fonction d'embedding avec le modèle spécifié."""
        return ChromaEmbeddingFunction(model or self.embedding_model)
    
    def _get_or_create_collection(self, collection_name: str) -> Collection:
        """
        Récupère ou crée une collection dans le cache.
        """
        if collection_name not in self._collections_cache:
            embedding_function = self._create_embedding_function()
            
            self._collections_cache[collection_name] = self.client.get_or_create_collection(
                name=collection_name,
                embedding_function=embedding_function,
                configuration={"hnsw": DEFAULT_HNSW_CONFIG}
            )
        
        return self._collections_cache[collection_name]
    
    def _get_collection(self, collection_name: str = None) -> Collection:
        """
        Récupère une collection par son nom.
        """
        name = collection_name or self.default_collection_name
        return self._get_or_create_collection(name)
    
    def add_memory(self, text: str, collection_name: str, metadata: Dict[str, Any] = None) -> str:
        """
        Ajoute une mémoire à une collection.
        """
        collection = self._get_collection(collection_name)
        memory_id = str(uuid.uuid4())
        
        now = datetime.now().isoformat()
        default_metadata = {
            "created_at": now,
            "updated_at": now
        }
        final_metadata = {**default_metadata, **(metadata or {})}
        
        collection.add(
            ids=[memory_id],
            documents=[text],
            metadatas=[final_metadata]
        )
        
        return memory_id
    
    def add_memories(self, collection_name: str, texts: List[str], metadatas: List[Dict[str, Any]] = None, embeddings: List = None, custom_ids: List[str] = None) -> List[str]:
        """
        Ajoute plusieurs mémoires à une collection.
        """
        if len(texts) == 0:
            return []
        
        collection = self._get_collection(collection_name)

        memory_ids = custom_ids if custom_ids is not None else [str(uuid.uuid4()) for _ in texts]
        
        now = datetime.now().isoformat()
        default_metadatas = [
            {
                "created_at": now,
                "updated_at": now,
            }
            for _ in texts
        ]
        final_metadatas = []
        if metadatas and len(metadatas) == len(texts):
            for i, metadata in enumerate(metadatas):
                final_metadata = {**default_metadatas[i], **(metadata or {})}
                final_metadatas.append(final_metadata)
        else:
            final_metadatas = default_metadatas

        if (embeddings):
            collection.add(
                ids=memory_ids,
                documents=texts,
                embeddings=embeddings,
                metadatas=final_metadatas
            )
        else:
            collection.add(
                ids=memory_ids,
                documents=texts,
                metadatas=final_metadatas
            )
        
        return memory_ids
    
    def get_memory(self, memory_id: str, collection_name: str = None) -> Optional[Dict[str, Any]]:
        """
        Récupère une mémoire par son ID dans une collection.
        """
        collection = self._get_collection(collection_name)
        
        result = collection.get(
            ids=[memory_id],
            include=["documents", "metadatas", "embeddings"]
        )
        
        if not result or not result.get("documents") or len(result["documents"]) == 0:
            return None
        
        return {
            "id": memory_id,
            "document": result["documents"][0] if result["documents"] else None,
            "metadata": result["metadatas"][0] if result["metadatas"] else {},
            "embedding": result["embeddings"][0] if result["embeddings"] else None,
            "collection": collection_name or self.default_collection_name
        }
    
    def get_memories(self, memory_ids: List[str] = None, limit: int = None, include_embeddings: bool = False, collection_name: str = None) -> List[Dict[str, Any]]:
        """
        Récupère plusieurs mémoires d'une collection.
        """
        collection = self._get_collection(collection_name)
        
        include_list = ["documents", "metadatas"]
        if include_embeddings:
            include_list.append("embeddings")
        
        if memory_ids:
            result = collection.get(
                ids=memory_ids,
                include=include_list
            )
        else:
            result = collection.get(
                limit=limit,
                include=include_list
            )
        
        memories = []
        documents = result.get("documents", [])
        metadatas = result.get("metadatas", [])
        embeddings = result.get("embeddings", [])
        ids = result.get("ids", [])
        collection_label = collection_name or self.default_collection_name
        
        for i in range(len(documents)):
            memory = {
                "id": ids[i] if i < len(ids) else None,
                "document": documents[i],
                "metadata": metadatas[i] if i < len(metadatas) else {},
                "collection": collection_label
            }
            if include_embeddings and i < len(embeddings):
                memory["embedding"] = embeddings[i]
            memories.append(memory)
        
        return memories
    
    def get_all_memories(self, include_embeddings: bool = False, collection_name: str = None) -> List[Dict[str, Any]]:
        """
        Récupère toutes les mémoires d'une collection.
        """
        return self.get_memories(
            include_embeddings=include_embeddings,
            collection_name=collection_name
        )
    
    def delete_memory(self, memory_id: str, collection_name: str = None) -> bool:
        """
        Supprime une mémoire par son ID dans une collection.
        """
        try:
            collection = self._get_collection(collection_name)
            collection.delete(ids=[memory_id])
            return True
        except Exception as e:
            print(f"Erreur lors de la suppression de la mémoire {memory_id} dans {collection_name or self.default_collection_name}: {e}")
            return False
    
    def delete_memories(self, memory_ids: List[str], collection_name: str = None) -> bool:
        """
        Supprime plusieurs mémoires dans une collection.
        """
        try:
            collection = self._get_collection(collection_name)
            collection.delete(ids=memory_ids)
            return True
        except Exception as e:
            print(f"Erreur lors de la suppression des mémoires dans {collection_name or self.default_collection_name}: {e}")
            return False
    
    def delete_all_memories(self, collection_name: str = None) -> bool:
        """
        Supprime toutes les mémoires d'une collection.
        """
        try:
            collection = self._get_collection(collection_name)
            all_memories = self.get_all_memories(collection_name=collection_name)
            all_ids = [m["id"] for m in all_memories if m["id"]]
            if all_ids:
                collection.delete(ids=all_ids)
            return True
        except Exception as e:
            print(f"Erreur lors de la suppression de toutes les mémoires dans {collection_name or self.default_collection_name}: {e}")
            return False
    
    def search_memories(self, collection_name: str, query: str, n_results: int = 10, include_metadata: bool = False, include_documents: bool = True, include_distances: bool = False, where: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Recherche des mémoires similaires à une requête dans une collection.
        """
        collection = self._get_collection(collection_name)
        
        include = []
        if include_documents:
            include.append("documents")
        if include_metadata:
            include.append("metadatas")
        if include_distances:
            include.append("distances")
        
        result = collection.query(
            query_texts=[query],
            n_results=n_results,
            include=include,
            where=where
        )
        
        return result
    
    def update_memory(self, memory_id: str, collection_name: str, new_text: str = None, new_metadata: Dict[str, Any] = None) -> bool:
        """
        Met à jour une mémoire existante dans une collection.
        """
        try:
            collection = self._get_collection(collection_name)
            collection.update(
                ids=[memory_id],
                metadatas=[new_text],
                documents=[new_text]
            )
        except Exception as e:
            print(f"Erreur lors de la mise à jour de la mémoire {memory_id} dans {collection_name or self.default_collection_name}: {e}")
            return False
    
    def get_collection_stats(self, collection_name: str = None) -> Dict[str, Any]:
        """
        Récupère les statistiques d'une collection.
        """
        all_memories = self.get_all_memories(collection_name=collection_name)
        name = collection_name or self.default_collection_name
        return {
            "total_memories": len(all_memories),
            "collection_name": name
        }
    
    def delete_collection(self, name: str):
        try:
            self.client.delete_collection(name)
            print(f"Collection {name} deleted")
        except:
            print(f"ERROR: Collection {name} can not be deleted")
            

# Instance singleton par défaut
def get_chroma_service(host: str = 'localhost', port: int = 8001, default_collection_name: str = "memories") -> ChromaService:
    """
    Retourne une instance du service Chroma.
    
    Args:
        host: Hôte du serveur Chroma
        port: Port du serveur Chroma
        default_collection_name: Nom de la collection par défaut
        
    Returns:
        Instance de ChromaService
    """
    return ChromaService(
        host=host,
        port=port,
        default_collection_name=default_collection_name
    )