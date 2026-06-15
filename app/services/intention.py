from app.services.ollama import call_ollama
from app.prompts.intention import build_intent_prompt, INTENT_SYSTEM_PROMPT

INTENTIONS = {"salutation", "aide", "recherche", "affinage", "hors_perimetre", "incomprehensible"}

async def classify_intention(message: str, historique: list[dict]) -> str:
    prompt = f"Message à classifier: {message}\n"

    result = await call_ollama(prompt=prompt, system=INTENT_SYSTEM_PROMPT)
    intent = result.strip().lower()

    return intent if intent in INTENTIONS else "hors_perimetre"