import requests
import numpy as np
import json
from app.prompts.recherche_semantique_text import RECHERCHE_SEMANTIQUE_TEXT_PROMPT
from app.services.database import get_connection
from app.services.ollama import call_ollama
from app.config import settings
from bs4 import BeautifulSoup

def remove_html_tags(text):
    if text is None:
        return ""
    soup = BeautifulSoup(text, "html.parser")
    return soup.get_text(separator=" ", strip=True)

def get_embedding(text: str) -> list[float]:
    instruction = "Given a support ticket search query, retrieve relevant support tickets that match the topic or subject of the query"
    text = f"Instruct: {instruction}\nQuery:{text}"
    response = requests.post(settings.ollama_url_embedding, json={"model": settings.model_ia_embedding, "input": text})
    response.raise_for_status()
    return response.json()["embeddings"]

def cosine_similarity(a, b):
    a, b = np.array(a), np.array(b)
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

def search(query: str, seuil: int):
    query_emb = get_embedding(query)[0]
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT ticket_id, embedding_v2 FROM ticket_embedding")
    rows = cursor.fetchall()

    scored = []
    for row in rows:
        emb = json.loads(row['embedding_v2'])[0]
        score = cosine_similarity(query_emb, emb)
        if score >= seuil:
            scored.append((row['ticket_id'], score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored

async def embedding_service(text: str):
    cleaned_text = await call_ollama(prompt=f"Message: {text}", system=RECHERCHE_SEMANTIQUE_TEXT_PROMPT)
    print(f"Cleaned text: {cleaned_text}")
    results = search(cleaned_text, 0.5)
    ticket_ids = tuple([ticket_id for ticket_id, score in results])
    ticket_scores = {ticket_id: score for ticket_id, score in results}

    if (len(ticket_ids) == 0):
        return "SELECT id, summary, description FROM ticket WHERE 0"
    
    conn = get_connection()
    cursor = conn.cursor()
    query = "SELECT id, summary, description FROM ticket WHERE id IN ({})".format(
        ", ".join(["%s"] * len(ticket_ids))
    )
    cursor.execute(query, ticket_ids)
    rows = cursor.fetchall()
    sql = query % tuple(ticket_ids)
    
    for row in rows:
        ticket_id = row['id']
        score = ticket_scores.get(ticket_id, 0) 
        print(f"Ticket {ticket_id} (Score: {score:.4f})")
        print(f"Titre: {row['summary']}")
        print(f"Description: {remove_html_tags(row['description'])}\n")
        print("---")
    
    return sql