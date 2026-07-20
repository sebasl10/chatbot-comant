"""Tools mémoire (souvenirs / corrections), backed Chroma.

Stockage dans la collection Chroma ``memories`` (filtrage par métadonnées
``type``/``scope``/``user_id`` + recherche sémantique). Signatures inchangées
depuis la Phase 1 : seul le backend a changé (Markdown → Chroma).

Types de mémoire : correction_sql, expand_vocabulary (global), exclude_ticket,
other_correction.
"""

import asyncio
from pydantic_ai import RunContext
from app.agents.deps import ChatDeps
from app.services import vectorstore as vs

VALID_MEMORY_TYPES = ("correction_sql", "expand_vocabulary", "exclude_ticket", "other_correction")


async def get_memory(ctx: RunContext[ChatDeps], type: str, query: str | None = None) -> str:
    """
    Récupère les souvenirs mémorisés de l'utilisateur pour un `type` donné.

    Types valides : correction_sql (règles de correction SQL), expand_vocabulary
    (synonymes/vocabulaire, global), exclude_ticket (tickets à exclure),
    other_correction. Si `query` est fourni, renvoie les souvenirs les plus
    pertinents sémantiquement ; sinon tous ceux du type. Vide si aucun.
    
    Pour expand_vocabulary : retourne les synonymes formatés pour le prompt.
    """
    print("[TOOL CALL] get_memory")
    print(f"  Type: {type}, Query: {query}")
    
    if type not in VALID_MEMORY_TYPES:
        return ""
    
    """     
    if type == "expand_vocabulary":
        if query:
            vocabulary = await asyncio.to_thread(vs.get_vocabulary_for_term, query)
            synonyms = vocabulary["synonyms"]
            print(f"  [SYNONYMS FOUND] Pour '{query}': {synonyms}")
            if synonyms:
                return f"Synonymes pour '{query}': {', '.join(synonyms)}"
            else:
                print(f"  [NO SYNONYMS] Aucun synonyme trouvé pour '{query}'")
                return ""
        else:
            all_memories = await asyncio.to_thread(vs.get_all_synonyms)
            print(f"  [ALL SYNONYMS] {len(all_memories)} entrées expand_vocabulary trouvés")
            if all_memories:
                formatted = "\n".join([f"{entry['base_term']}: {entry['synonyms']}" for entry in all_memories])
                return f"Vocabulaire étendu:\n{formatted}"
            return "" 
    """
    
    # Pour les autres types, utiliser l'ancienne méthode
    return await asyncio.to_thread(vs.get_memories_text, type, ctx.deps.user_id, query)


async def save_memory(ctx: RunContext[ChatDeps], type: str, content: str, base_term: str | None = None) -> dict:
    """Enregistre un nouveau souvenir de `type` donné pour l'utilisateur.

    À utiliser quand l'utilisateur corrige le comportement du chatbot ou ajoute
    une règle/synonyme à retenir. Types valides : correction_sql, expand_vocabulary,
    exclude_ticket, other_correction.
    
    Pour expand_vocabulary:
        - content : les synonymes séparés par des virgules (ex: "lent, slow, rapide")
        - base_term : le terme de base (ex: "performance")
    """
    if type not in VALID_MEMORY_TYPES:
        return {"ok": False, "error": f"type invalide: {type}"}
    
    # Pour expand_vocabulary, utiliser la nouvelle structure
    if type == "expand_vocabulary" and base_term:
        # Convertir content en liste de synonymes
        synonyms = [s.strip() for s in content.split(",") if s.strip()]
        print(f"[SAVE MEMORY] expand_vocabulary - base_term: '{base_term}', synonyms: {synonyms}")
        await asyncio.to_thread(
            vs.add_synonyms, base_term, synonyms, ctx.deps.user_id, ctx.deps.username
        )
        ctx.deps.events.correction(type=type, memory=f"{base_term}: {content}")
    else:
        print(f"[SAVE MEMORY] type: {type}, content: {content}")
        await asyncio.to_thread(
            vs.add_memory, type, content, ctx.deps.user_id, ctx.deps.username
        )
        ctx.deps.events.correction(type=type, memory=content)
    
    return {"ok": True, "type": type}


async def delete_memory(ctx: RunContext[ChatDeps]) -> dict:
    """
    Supprime le dernier souvenir créé
    """
    print("[TOOL CALL] delete_memory")
    last_memory = vs.get_last_memory(ctx.deps.user_id)
    
    if not last_memory:
        return {"ok": False, "error": "Aucun souvenir récent à supprimer."}
    
    print(f"Memory ID: {last_memory['id']}")
    print(f"Memory Content: {last_memory['content']}")
    
    try:
        await asyncio.to_thread(vs.delete_memory, last_memory['id'], ctx.deps.user_id)
        ctx.deps.events.action("delete_memory", memory_id=last_memory['id'])
        return {"ok": True, "message": "Souvenir supprimé.", "content": last_memory['content']}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def update_memory(ctx: RunContext[ChatDeps], new_content: str) -> dict:
    """
    Met à jour le dernier souvenir créé (utilise ctx.deps.last_memory_id).
    Args:m
        new_content: Nouveau contenu du souvenir
    """
    print("[TOOL CALL] update_memory")
    last_memory = vs.get_last_memory(ctx.deps.user_id)
    print(f"Memory ID: {last_memory['id']}")
    print(f"Memory Content: {last_memory['content']}")
    if not last_memory:
        return {"ok": False, "error": "Aucun souvenir récent à modifier."}
    print(f"Nouveau contenu: {new_content}")
    try:
        success = await asyncio.to_thread(
            vs.update_memory, last_memory['id'], new_content, ctx.deps.user_id, ctx.deps.username
        )
        if success:
            ctx.deps.events.action("update_memory", memory_id=last_memory['id'])
            return {"ok": True, "message": "Souvenir mis à jour.", "old_content": last_memory['content'], "new_content": new_content}
        else:
            return {"ok": False, "error": "Souvenir non trouvé."}
    except Exception as e:
        return {"ok": False, "error": str(e)}