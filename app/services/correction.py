from app.prompts.correction import CORRECTION_PROMPT
from app.services.ollama import call_ollama
from app.services.memory_md import save_memory_to_md
import json

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


async def correction_service(message: str, historique: list[dict], user_id: int) -> dict:
    """
    Analyse le message et l'historique pour identifier le type de correction et générer un souvenir structuré.
    
    Returns:
        dict: {"type": "...", "memory": "..."}
    """
    historique_str = json.dumps(historique, ensure_ascii=False)
    prompt = f"Historique: {historique_str}\nDernier message: {message}"

    response = await call_ollama(prompt=prompt, system=CORRECTION_PROMPT)

    response = clean_json(response)
    result = json.loads(response)

    await save_memory_to_md(result, user_id)

    return result