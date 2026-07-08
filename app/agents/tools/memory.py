"""
Tools mémoire (souvenirs / corrections), backed Chroma.

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
    Si `query` est fourni, renvoie les souvenirs les plus pertinents sémantiquement ; sinon tous ceux du type. Vide si aucun.
    """
    if type not in VALID_MEMORY_TYPES:
        return ""
    return await asyncio.to_thread(vs.get_memories_text, type, ctx.deps.user_id, query)


async def save_memory(ctx: RunContext[ChatDeps], type: str, content: str) -> dict:
    """
    Enregistre un nouveau souvenir de `type` donné pour l'utilisateur.
    Args:
        type: Type de souvenir
        Content: Souvenir à stocker
    """
    print("[TOOL CALL] save_memory")
    print(f"Type: {type}")
    print(f"Contenu: {content}")
    if type not in VALID_MEMORY_TYPES:
        return {"ok": False, "error": f"type invalide: {type}"}
    memory_id = await asyncio.to_thread(
        vs.add_memory, type, content, ctx.deps.user_id, ctx.deps.username
    )
    ctx.deps.events.correction(type=type, memory=content)
    return {"ok": True, "type": type, "content": content, "memory_id": memory_id}


async def delete_memory(ctx: RunContext[ChatDeps]) -> dict:
    """
    Supprime le dernier souvenir créé
    """
    print("[TOOL CALL] delete_memory")
    last_memory = vs.get_last_memory(ctx.deps.user_id)
    print(f"Memory ID: {last_memory['id']}")
    print(f"Memory Content: {last_memory['content']}")
    if not last_memory:
        return {"ok": False, "error": "Aucun souvenir récent à supprimer."}
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
