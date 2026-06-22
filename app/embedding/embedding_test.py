import numpy as np
import json
from app.embedding.embedding_generation import get_embedding
from app.services.database import get_connection
from bs4 import BeautifulSoup

def remove_html_tags(text):
    soup = BeautifulSoup(text, "html.parser")
    return soup.get_text(separator=" ", strip=True)

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

# Test
def main():
    print("Début Test")
    query_emb = get_embedding("cinematique")[0]
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT ticket_id, embedding, ticket.summary, ticket.description FROM `ticket_embedding` JOIN ticket ON ticket_embedding.ticket_id = ticket.id WHERE ticket.description like '%cinematique%'")
    rows = cursor.fetchall()
    for row in rows:
        emb = json.loads(row['embedding'])[0]
        score = cosine_similarity(query_emb, emb)
        print(f"Ticket {row['ticket_id']}:")
        print(f"Score: {score}")
        print(f"Summary: {row['summary']}")
        print(f"Description: {remove_html_tags(row['description'])}")
        print("")
    
    """ results = search("les tickets qui parlent de cinématique")
    ticket_ids = tuple([ticket_id for ticket_id, score in results])

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, summary, description FROM ticket WHERE id IN %s", (ticket_ids,))
    rows = cursor.fetchall()
    
    for row in rows:
        print(f"Ticket {row['id']}:")
        print(f"Titre: {row['summary']}")
        print(f"Description: {row['description']}\n")
        print("---")  """
        
    

if __name__ == "__main__":
    main()