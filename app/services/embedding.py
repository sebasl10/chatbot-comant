import json
import ast
from app.prompts.recherche_semantique_text import build_recherche_semantique_text_prompt
from app.prompts.ticket_exclusion import build_ticket_exclusion_prompt
from app.services.database import get_connection
from app.services.ollama import call_ollama
from app.services.memory_md import get_memories
from app.services.chroma_service import get_chroma_service
from app.config import settings
from bs4 import BeautifulSoup

def remove_html_tags(text):
    if text is None:
        return ""
    soup = BeautifulSoup(text, "html.parser")
    return soup.get_text(separator=" ", strip=True)

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
    """ system_prompt = build_recherche_semantique_text_prompt(expand_vocabulary_memories)
    cleaned_text = await call_ollama(prompt=f"Message: {text}", system=system_prompt)
    print(f"Cleaned text: {cleaned_text}") """
    
    # Étape 2 : Recherche sémantique avec Chroma
    chroma_service = get_chroma_service()
    results = chroma_service.search_memories(
        query=text,
        n_results=10,
        include_metadata=True,
        include_distances=True,
        collection_name="tickets"
    )
    
    # Extraire ticket_ids et scores depuis les métadonnées
    ticket_ids = []
    ticket_scores = {}
    
    if results and "metadatas" in results and len(results["metadatas"]) > 0:
        for i, metadata in enumerate(results["metadatas"][0]):
            if metadata and "ticket_id" in metadata:
                ticket_id = metadata["ticket_id"]
                distance = results["distances"][0][i] if "distances" in results else 0.0
                similarity_score = 1.0 - distance
                
                if similarity_score >= 0.5:
                    ticket_ids.append(ticket_id)
                    ticket_scores[ticket_id] = similarity_score
    print(f"\n{'─' * 60}\n[SEMANTIC RESEARCH TICKETS]\n{ticket_scores}\n{'─' * 60}")

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
