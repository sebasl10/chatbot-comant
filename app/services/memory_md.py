import os
from datetime import datetime


async def get_correction_sql_memories(user_id: int) -> str:
    """
    Récupère les souvenirs de type correction_sql pour un utilisateur.
    
    Args:
        user_id: identifiant de l'utilisateur
    
    Returns:
        str: Le contenu du fichier correction_sql.md ou chaîne vide
    """
    file_path = os.path.join("app", "memory", str(user_id), "correction_sql.md")
    
    if not os.path.exists(file_path):
        return ""
    
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()


async def save_memory_to_md(correction_data: dict, user_id: int):
    """
    Sauvegarde le souvenir dans un fichier MD dans le dossier app/memory/{user_id}.
    Il y a 4 fichiers, un pour chaque type de souvenir.
    
    Args:
        correction_data: dict avec clés "type" et "memory"
        user_id: identifiant de l'utilisateur
    """
    memory_type = correction_data["type"]
    memory_content = correction_data["memory"]
    
    valid_types = ["correction_sql", "expand_vocabulary", "exclude_ticket", "other_correction"]
    if memory_type not in valid_types:
        raise ValueError(f"Type de mémoire invalide: {memory_type}")
    
    base_path = os.path.join("app", "memory", str(user_id))
    os.makedirs(base_path, exist_ok=True)
    
    filename = os.path.join(base_path, f"{memory_type}.md")
    
    current_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    with open(filename, "a", encoding="utf-8") as f:
        f.write(f"## {current_date}\n\n")
        f.write(f"{memory_content}\n\n")
        f.write("---\n\n")

    print("[MEMORY SAVED]")
    
    return filename
