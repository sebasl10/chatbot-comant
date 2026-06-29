from app.prompts.verify_memories import build_verify_memories_prompt

async def verify_sql_against_memories(message: str, sql_query: str, memories: list[str], user_id: int | None = None) -> str:
    """
    Vérifie et modifie si nécessaire la requête SQL pour qu'elle respecte les mémoires de l'utilisateur.
    Retourne UNIQUEMENT la requête SQL (modifiée ou originale).
    """
    from app.services.ollama import call_ollama
    
    system_prompt = build_verify_memories_prompt(message, sql_query, memories, user_id)
    user_prompt = f"Message: {message}\nRequête SQL: {sql_query}"
    
    response = await call_ollama(prompt=user_prompt, system=system_prompt)
    
    # Nettoyer la réponse pour s'assurer qu'il n'y a que du SQL
    cleaned = response.strip()
    
    # Supprimer les éventuels backticks ou markdown
    if cleaned.startswith("```sql"):
        cleaned = cleaned[7:].strip()
    if cleaned.startswith("```"):
        cleaned = cleaned[3:].strip()
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3].strip()
    
    return cleaned
