import requests
import numpy as np
import json
from app.prompts.recherche_semantique_text import RECHERCHE_SEMANTIQUE_TEXT_PROMPT
from app.services.database import get_connection
from app.services.ollama import call_ollama
from app.config import settings

def get_embedding(text: str) -> list[float]:
    response = requests.post(settings.ollama_url_embedding, json={"model": settings.model_ia_embedding, "input": text})
    response.raise_for_status()
    return response.json()["embeddings"]

def cosine_similarity(a, b):
    a, b = np.array(a), np.array(b)
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

def search(query: str, top_k=5):
    query_emb = get_embedding(query)[0]
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT ticket_id, embedding FROM ticket_embedding")
    rows = cursor.fetchall()

    scored = []
    for row in rows:
        emb = json.loads(row['embedding'])[0]
        score = cosine_similarity(query_emb, emb)
        scored.append((row['ticket_id'], score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]

async def embedding_service(text: str):
    cleaned_text = await call_ollama(prompt=f"Message: {text}", system=RECHERCHE_SEMANTIQUE_TEXT_PROMPT)
    print(f"Cleaned text: {cleaned_text}")
    results = search(cleaned_text)
    ticket_ids = tuple([ticket_id for ticket_id, score in results])

    conn = get_connection()
    cursor = conn.cursor()
    query = "SELECT id, summary, description FROM ticket WHERE id IN ({})".format(
        ", ".join(["%s"] * len(ticket_ids))
    )
    cursor.execute(query, ticket_ids)
    rows = cursor.fetchall()
    sql = query % tuple(ticket_ids)
    
    for row in rows:
        print(f"Ticket {row['id']}:")
        print(f"Titre: {row['summary']}")
        print(f"Description: {row['description']}\n")
        print("---")
    
    return sql