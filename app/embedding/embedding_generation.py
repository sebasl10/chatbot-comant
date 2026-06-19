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

    insert_cursor = conn.cursor()
    for ticket in tickets:
        text = f"{ticket['summary']}\n{ticket['description'] or ''}"
        embedding = get_embedding(text)
        insert_cursor.execute(
            """INSERT INTO ticket_embedding (ticket_id, embedding_v2)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE embedding_v2 = %s""",
            (ticket['id'], json.dumps(embedding), json.dumps(embedding))
        )
        print(f"Ticket {ticket['id']} embedded ({len(embedding)} dims)")

    conn.commit()
    cursor.close()
    insert_cursor.close()
    conn.close()

if __name__ == "__main__":
    main()
