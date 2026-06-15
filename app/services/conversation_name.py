from app.services.ollama import call_ollama
from app.prompts.conversation_name import CONVERSATION_NAME_SYSTEM_PROMPT
from app.services.database import update_conversation_name

async def create_name(conversation_id: int, historique: list):
    prompt = f"\nMessages de l'utilisateur: {historique}\nGenère le nom de la conversation: "
    name = await call_ollama(prompt=prompt, system=CONVERSATION_NAME_SYSTEM_PROMPT)
    print(name)
    update_conversation_name(conversation_id, str(name))
    return name
