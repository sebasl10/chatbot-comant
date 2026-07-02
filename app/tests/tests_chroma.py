import chromadb
import uuid
import requests
from datetime import datetime
from pathlib import Path
from typing import Dict, Any
from chromadb import Documents, EmbeddingFunction, Embeddings
from chromadb.utils.embedding_functions import register_embedding_function
from app.config import settings

client = chromadb.HttpClient(host='localhost', port=8000)

@register_embedding_function
class MyEmbeddingFunction(EmbeddingFunction):
    def __init__(self, model):
        self.model = model

    def __call__(self, input: Documents) -> Embeddings:
        texts = [f"Query:{text}" for text in input]
        response = requests.post(
            settings.ollama_url_embedding, 
            json={"model": self.model, "input": texts}
        )
        response.raise_for_status()
        embeddings = response.json()["embeddings"]
        return embeddings

    @staticmethod
    def name() -> str:
        return "my-ef"

    def get_config(self) -> Dict[str, Any]:
        return dict(model=self.model)

    @staticmethod
    def build_from_config(config: Dict[str, Any]) -> "EmbeddingFunction":
        return MyEmbeddingFunction(config['model'])

embedding_function = MyEmbeddingFunction(settings.model_ia_embedding)

collection = client.get_or_create_collection(
    name="memories", 
    embedding_function=embedding_function,
    configuration={
        "hnsw": {
            "space": "cosine",
            "ef_construction": 1000,
            "ef_search": 1000
        }
    }
)
#print(collection.get(include=["documents"]))
#print(client.list_collections())

""" script_dir = Path(__file__).parent
with open(script_dir / "test_memories.txt", "r", encoding="utf-8") as f:
    memories: list[str] = f.read().splitlines()

collection.add(
    ids=[str(uuid.uuid4()) for _ in memories],
    documents=memories,
    metadatas=[
        {"line": idx, "date": datetime.now().isoformat()}  for idx in range(len(memories))
    ]
)
 """
# Vérifier que les documents et embeddings sont bien stockés
print("\n=== Vérification du stockage ===")
stored_items = collection.get(
    include=["documents", "embeddings", "metadatas"]
)
print(f"Nombre de documents stockés: {len(stored_items['documents'])}")
print(f"Nombre d'embeddings stockés: {len(stored_items['embeddings'])}")
if len(stored_items['embeddings']) > 0:
    print(f"Taille des embeddings: {len(stored_items['embeddings'][0])} dimensions")
    print(f"Exemple d'embedding (5 premières valeurs): {stored_items['embeddings'][0][:5]}")

query_texts = [
    "Quels sont les logiciels utilisés par CoreTechnologie?",
    "Combien d'employés a CoreTechnologie?"
]
results = collection.query(
    query_texts=query_texts,
    n_results=10,
    include=["documents", "metadatas", "embeddings", "distances"],
)
#print(results)

""" print("\n=== Clés disponibles dans results ===")
print(f"Keys: {list(results.keys())}") """

print("\n=== Résultats de la requête ===")
distance_key = "distances" if "distances" in results else "scores"
for i, query_results in enumerate(results["documents"]):
    print(f"\nQuery {i}: {query_texts[i]}")
    for j, doc in enumerate(query_results):
        distance_val = results[distance_key][i][j]
        print(f"  {j+1}. {doc} ({distance_key}: {distance_val:.4f})")