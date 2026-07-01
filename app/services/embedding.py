import requests
import numpy as np
import json
import ast
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

def clean_json(text: str):
    """Nettoie le texte pour extraire le JSON."""
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:].strip()
    if text.startswith("```"):
        text = text[3:].strip()
    if text.endswith("```"):
        text = text[:-3].strip()
    return text

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
    print(f"\n{'─' * 60}\n[BASE QUERY]\n{base_query}\n{'─' * 60}")
    
    # Étape 3 : Appliquer les mémoires d'exclusion (codes de tickets, pas IDs)
    exclude_memories = await get_memories(user_id, "exclude_ticket")
    if exclude_memories:
        print(f"\n{'─' * 60}\n[EXCLUDE TICKET MEMORIES]\n{exclude_memories}\n{'─' * 60}")
        
        system_prompt = build_ticket_exclusion_prompt(exclude_memories)
        prompt = f"Recherche de l'utilisateur: {text}"
        
        codes_to_exclude_str = await call_ollama(prompt=prompt, system=system_prompt)
        codes_to_exclude_str = clean_json(codes_to_exclude_str)
        print(f"\n{'─' * 60}\n[CODES TO EXCLUDE]\n{codes_to_exclude_str}\n{'─' * 60}")
        
        codes_to_exclude_str = codes_to_exclude_str.strip()
        try:
            codes_to_exclude = ast.literal_eval(codes_to_exclude_str)
            if not isinstance(codes_to_exclude, list):
                codes_to_exclude = []
        except (ValueError, SyntaxError):
            codes_to_exclude = []
        
        if codes_to_exclude:
            formatted_codes = ", ".join(f"'{code}'" for code in codes_to_exclude)
            exclusion_clause = f" AND t.code NOT IN ({formatted_codes})"
            base_query = base_query.rstrip()
            base_query = base_query + exclusion_clause
        
        print(f"\n{'─' * 60}\n[FINAL QUERY]\n{base_query}\n{'─' * 60}")
    
    # Étape 4 : Exécuter la requête finale et afficher les résultats
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(base_query)
    rows = cursor.fetchall()

    """ for row in rows:
        ticket_id = row['id']
        score = ticket_scores.get(ticket_id, 0) 
        print(f"Ticket {ticket_id} (Score: {score:.4f})")
        print(f"Titre: {row['summary']}")
        print(f"Description: {remove_html_tags(row['description'])}\n")
        print("---") """
    
    return base_query
