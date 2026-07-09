import json

def _history_context(historique: list[dict]) -> str:
    """
    Formate l'historique au format JSON pour injection dans le prompt d'un LLM.
    """
    if not historique:
        return ""

    recent_messages = []
    for msg in historique:
        role = msg.get("sender_role") or msg.get("role") or "user"
        content = msg.get("content") or msg.get("contenu") or ""
        if content.strip():
            recent_messages.append({"role": role, "content": content})

    if not recent_messages:
        return ""

    return (
        "Historique de la conversation (récent, format JSON) :\n"
        + json.dumps(recent_messages, ensure_ascii=False, indent=2)
        + "\n\n"
    )
