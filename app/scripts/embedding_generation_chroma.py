"""
Script pour migrer les tickets de la base de données vers une collection Chroma "tickets".

Ce script:
1. Récupère tous les tickets et leurs commentaires de la base de données
2. Construit le texte complet (summary + description + commentaires)
3. Récupère les embeddings pré-calculés de ticket_embedding
4. Ajoute chaque ticket avec son embedding à la collection Chroma "tickets"
"""

import json
from bs4 import BeautifulSoup
from app.services.database import get_connection
from app.services import vectorstore

def remove_html_tags(text):
    """Nettoie le texte en supprimant les balises HTML."""
    if text is None:
        return ""
    soup = BeautifulSoup(text, "html.parser")
    return soup.get_text(separator=" ", strip=True)


def get_ticket_text(ticket, comments_by_ticket):
    """
    Construit le texte complet d'un ticket (summary + description + commentaires).
    """
    text_parts = []
    
    if ticket['summary']:
        text_parts.append(remove_html_tags(ticket['summary']))

    if ticket['description']:
        text_parts.append(remove_html_tags(ticket['description']))

    ticket_id = ticket['id']
    if ticket_id in comments_by_ticket:
        for comment in comments_by_ticket[ticket_id]:
            text_parts.append(remove_html_tags(comment))
    
    return "\n".join(text_parts)


def main():
    """Exécute la migration des tickets vers Chroma avec embeddings pré-calculés."""
    print("=== Début de la migration des tickets vers Chroma ===\n")

    conn = get_connection()

    vectorstore.get_client().delete_collection('tickets')
    
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, summary, description FROM ticket WHERE ticket.type IN ('Bug', 'Dev', 'Suggestion', 'Requête', 'Documentation')")
        tickets = cursor.fetchall()
        print(f"Trouvé {len(tickets)} tickets à migrer")
        
        comments_cursor = conn.cursor()
        comments_cursor.execute("SELECT ticket_id, text FROM comment")
        comments = comments_cursor.fetchall()
        
        # Organise les commentaires par ticket_id
        comments_by_ticket = {}
        for comment in comments:
            ticket_id = comment['ticket_id']
            if ticket_id not in comments_by_ticket:
                comments_by_ticket[ticket_id] = []
            comments_by_ticket[ticket_id].append(comment['text'])
        
        # Migration des tickets avec embeddings
        migrated_count = 0
        skipped_count = 0
        
        # Préparer les batches pour optimiser les insertions
        batch_size = 50
        current_batch = {
            'ids': [],
            'documents': [],
            'metadatas': []
        }
        
        for ticket in tickets:
            ticket_id = ticket['id']
            full_text = get_ticket_text(ticket, comments_by_ticket)
            
            # Vérifie si le texte n'est pas vide
            if not full_text.strip():
                print(f"⚠️  Ticket {ticket_id} : texte vide, ignoré")
                skipped_count += 1
                continue
            
            # Ajoute au batch
            current_batch['ids'].append(str(ticket_id))
            current_batch['documents'].append(full_text)
            current_batch['metadatas'].append({
                "ticket_id": ticket_id,
                "source": "database_migration"
            })
            
            # Si le batch est plein, on l'ajoute
            if len(current_batch['ids']) >= batch_size:
                vectorstore.tickets_collection().add(
                    ids=current_batch['ids'],
                    documents=current_batch['documents'],
                    metadatas=current_batch['metadatas'],
                )
                migrated_count += len(current_batch['ids'])
                print(f"✅ Batch de {len(current_batch['ids'])} tickets ajouté")
                
                # Réinitialise le batch
                current_batch = {
                    'ids': [],
                    'documents': [],
                    'metadatas': []
                }
        
        # Ajoute le dernier batch s'il n'est pas vide
        if current_batch['ids']:
            vectorstore.tickets_collection().add(
                ids=current_batch['ids'],
                documents=current_batch['documents'],
                metadatas=current_batch['metadatas'],
            )
            migrated_count += len(current_batch['ids'])
            print(f"✅ Dernier batch de {len(current_batch['ids'])} tickets ajouté")
        
        # Statistiques
        print(f"\n=== Résumé de la migration ===")
        print(f"Tickets migrés avec embeddings: {migrated_count}")
        print(f"Tickets ignorés (texte vide): {skipped_count}")
        print(f"Total traité: {migrated_count + skipped_count}")
        
        # Vérifie la collection
        print(f"Collection 'tickets': {vectorstore.tickets_collection().count()} documents")
        
        print("\n✅ Migration terminée avec succès !")
        
    except Exception as e:
        print(f"\n❌ Erreur fatale lors de la migration: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Ferme les connexions
        cursor.close()
        comments_cursor.close()
        conn.close()


if __name__ == "__main__":
    main()