import requests
import json
from bs4 import BeautifulSoup
from app.services.database import get_connection

OLLAMA_URL = "http://localhost:11434/api/embed"
MODEL = "qwen3-embedding:4b"

def get_embedding(text: str) -> list[float]:
    text = remove_html_tags(text)
    response = requests.post(OLLAMA_URL, json={"model": MODEL, "input": text})
    response.raise_for_status()
    return response.json()["embeddings"]

def remove_html_tags(text):
    soup = BeautifulSoup(text, "html.parser")
    return soup.get_text(separator=" ", strip=True)

def main():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, summary, description FROM ticket WHERE ticket.type != 'Group'")
    tickets = cursor.fetchall()

    # Récupérer tous les commentaires pour chaque ticket
    comments_cursor = conn.cursor()
    comments_cursor.execute("SELECT ticket_id, text FROM comment")
    comments = comments_cursor.fetchall()

    # Organiser les commentaires par ticket_id
    comments_by_ticket = {}
    for comment in comments:
        ticket_id = comment['ticket_id']
        if ticket_id not in comments_by_ticket:
            comments_by_ticket[ticket_id] = []
        comments_by_ticket[ticket_id].append(comment['text'])

    # Générer les embeddings pour chaque ticket
    insert_cursor = conn.cursor()
    for ticket in tickets:
        # Construire le texte complet : summary + description + commentaires
        text_parts = []
        if ticket['summary']:
            text_parts.append(ticket['summary'])
        if ticket['description']:
            text_parts.append(ticket['description'])
            
        ticket_id = ticket['id']
        if ticket_id in comments_by_ticket:
            for comment in comments_by_ticket[ticket_id]:
                text_parts.append(comment)

        full_text = "\n".join(text_parts)

        embedding = get_embedding(full_text)
        insert_cursor.execute(
            """INSERT INTO ticket_embedding (ticket_id, embedding)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE embedding = %s""",
            (ticket_id, json.dumps(embedding), json.dumps(embedding))
        )
        print(f"Ticket {ticket_id} embedded ({len(embedding)} dims)")

    conn.commit()
    cursor.close()
    insert_cursor.close()
    conn.close()

if __name__ == "__main__":
    main()
