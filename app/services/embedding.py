import requests
import numpy as np
import json
from app.prompts.recherche_semantique_text import build_recherche_semantique_text_prompt
from app.prompts.ticket_exclusion import build_ticket_exclusion_prompt
from app.services.database import get_connection
from app.services.ollama import call_ollama
from app.services.memory_md import get_memories
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
    cursor.execute("SELECT ticket_id, embedding FROM ticket_embedding")
    rows = cursor.fetchall()

    scored = []
    for row in rows:
        emb = json.loads(row['embedding'])[0]
        score = cosine_similarity(query_emb, emb)
        if score >= seuil:
            scored.append((row['ticket_id'], score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


async def embedding_service(text: str, expand_vocabulary_memories: str, user_id: int):
    # Étape 1 : Nettoyer le texte avec les synonymes
    system_prompt = build_recherche_semantique_text_prompt(expand_vocabulary_memories)
    cleaned_text = await call_ollama(prompt=f"Message: {text}", system=system_prompt)
    print(f"Cleaned text: {cleaned_text}")
    
    # Étape 2 : Recherche sémantique
    results = search(cleaned_text, 0.5)
    ticket_ids = [ticket_id for ticket_id, score in results]
    ticket_scores = {ticket_id: score for ticket_id, score in results}

    if len(ticket_ids) == 0:
        base_query = "SELECT t.id, t.summary, t.description FROM ticket t WHERE 0"
        return base_query
    else:
        ids_str = ", ".join(str(tid) for tid in ticket_ids)
        base_query = f"SELECT t.id, t.summary, t.description FROM ticket t WHERE t.id IN ({ids_str})"
    
    # Étape 3 : Appliquer les mémoires d'exclusion (codes de tickets, pas IDs)
    exclude_memories = await get_memories(user_id, "exclude_ticket")
    if exclude_memories:
        print(f"\n{'─' * 60}\n[EXCLUDE TICKET MEMORIES]\n{exclude_memories}\n{'─' * 60}")
        
        system_prompt = build_ticket_exclusion_prompt(exclude_memories)
        modified_query = await call_ollama(prompt=f"Recherche de l'utilisateur: {text}\nRequête SQL actuelle: {base_query}", system=system_prompt)
        print(f"\n{'─' * 60}\n[MODIFIED QUERY]\n{modified_query}\n{'─' * 60}")
        
        modified_query = modified_query.strip()
        if modified_query.startswith("```sql"):
            modified_query = modified_query[6:].strip()
        if modified_query.startswith("```"):
            modified_query = modified_query[3:].strip()
        if modified_query.endswith("```"):
            modified_query = modified_query[:-3].strip()
        
        base_query = modified_query
    
    # Étape 4 : Exécuter la requête finale et afficher les résultats
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(base_query)
    rows = cursor.fetchall()

    for row in rows:
        ticket_id = row['id']
        score = ticket_scores.get(ticket_id, 0) 
        print(f"Ticket {ticket_id} (Score: {score:.4f})")
        print(f"Titre: {row['summary']}")
        print(f"Description: {remove_html_tags(row['description'])}\n")
        print("---")
    
    return base_query
