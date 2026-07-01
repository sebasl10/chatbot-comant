import os
from datetime import datetime
from app.services.database import get_username

# Dossier pour les mémoires globales (partagées entre tous les utilisateurs)
GLOBAL_MEMORY_DIR = os.path.join("app", "memory", "_global")


async def get_memories(user_id: int, type: str) -> str:
    """
    Récupère les souvenirs pour un utilisateur.
    Pour le type 'expand_vocabulary', retourne les mémoires globales.
    Pour les autres types, retourne les mémoires spécifiques à l'utilisateur.
    """
    # Si c'est une mémoire globale (expand_vocabulary)
    if type == "expand_vocabulary":
        global_file = os.path.join(GLOBAL_MEMORY_DIR, f"{type}.md")
        if os.path.exists(global_file):
            with open(global_file, "r", encoding="utf-8") as f:
                return f.read()
        return ""
    
    # Sinon, mémoire spécifique à l'utilisateur
    file = f"{type}.md"
    username = get_username(user_id)
    file_path = os.path.join("app", "memory", username, file)
    
    if not os.path.exists(file_path):
        return ""
    
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()


async def save_memory_to_md(correction_data: dict, user_id: int):
    """
    Sauvegarde le souvenir dans un fichier MD.
    - Pour 'expand_vocabulary': sauvegarde dans le dossier global (_global)
    - Pour les autres types: sauvegarde dans app/memory/{user_id}/
    
    Chaque souvenir est préfixé par l'username de l'utilisateur qui l'a ajouté.
    """
    memory_type = correction_data["type"]
    memory_content = correction_data["memory"]
    
    valid_types = ["correction_sql", "expand_vocabulary", "exclude_ticket", "other_correction"]
    if memory_type not in valid_types:
        raise ValueError(f"Type de mémoire invalide: {memory_type}")
    
    username = get_username(user_id)
    if not username:
        username = f"user_{user_id}"
    
    if memory_type == "expand_vocabulary":
        base_path = GLOBAL_MEMORY_DIR
    else:
        base_path = os.path.join("app", "memory", username)
    
    os.makedirs(base_path, exist_ok=True)
    
    filename = os.path.join(base_path, f"{memory_type}.md")
    
    current_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    memory_with_username = f"[Utilisateur: {username}] {memory_content}"
    
    with open(filename, "a", encoding="utf-8") as f:
        f.write(f"## {current_date}\n\n")
        f.write(f"{memory_with_username}\n\n")
        f.write("---\n\n")
    
    print("[MEMORY SAVED]")
    
    return filename
