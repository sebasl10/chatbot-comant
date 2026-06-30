from app.prompts.correction import CORRECTION_PROMPT
from app.services.ollama import call_ollama
import json
import os


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


async def correction_service(message: str, historique: list[dict]) -> dict:
    """
    Analyse le message et l'historique pour identifier le type de correction
    et générer un souvenir structuré.
    
    Returns:
        dict: {"type": "...", "memory": "..."}
    """
    # Construire le prompt avec l'historique et le message
    historique_str = json.dumps(historique, ensure_ascii=False)
    prompt = f"Historique: {historique_str}\nDernier message: {message}"
    
    # Appeler Ollama
    response = await call_ollama(prompt=prompt, system=CORRECTION_PROMPT)
    
    # Nettoyer et parser la réponse
    response = clean_json(response)
    result = json.loads(response)
    
    return result


async def save_memory_to_md(correction_data: dict, user_id: int):
    """
    Sauvegarde le souvenir dans un fichier MD dans le dossier memory.
    
    Args:
        correction_data: dict avec clés "type" et "memory"
        user_id: identifiant de l'utilisateur
    """
    memory_type = correction_data["type"]
    memory_content = correction_data["memory"]
    
    # Créer le chemin du dossier memory si nécessaire
    base_path = os.path.join("memory", str(user_id), memory_type)
    os.makedirs(base_path, exist_ok=True)
    
    # Créer un nom de fichier unique (timestamp)
    import time
    timestamp = int(time.time())
    filename = os.path.join(base_path, f"{timestamp}.md")
    
    # Écrire le contenu dans le fichier
    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"# Souvenir de correction\n\n")
        f.write(f"**Type:** {memory_type}\n\n")
        f.write(f"**Contenu:** {memory_content}\n\n")
        f.write(f"---\n\n")
        f.write(f"*Créé le: {time.strftime('%Y-%m-%d %H:%M:%S')}*\n")
    
    return filename
