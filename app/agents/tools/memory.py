"""Tools mémoire (souvenirs / corrections), backed Chroma.

Stockage dans la collection Chroma ``memories`` (filtrage par métadonnées
``target_agent``/``kind``/``scope``/``user_id`` + recherche
sémantique).

- Lecture : ``relevant_memories(ctx, target_agent)`` récupère en top-k
  sémantique les souvenirs destinés à un agent, à partir du message utilisateur
  brut (``ctx.deps.message``).
- Écriture : ``save_memory`` (appelé par l'agent memory, qui reformule les
  messages elliptiques « oui/non » à partir de l'historique avant de stocker).

target_agent : supervisor, sql_research, semantic_research, conversational.
kind         : sql_rule, exclude, vocabulary, routing, other.
retrieval    : invariant (toujours injecté) | contextual (indexé par la requête
               déclencheuse, récupéré par similarité). Voir get_memories_text.
"""

from pydantic_ai import RunContext
from app.agents.deps import ChatDeps
from app.services import vectorstore as vs

VALID_TARGET_AGENTS = ("supervisor", "sql_research", "semantic_research", "conversational")
VALID_KINDS = ("sql_rule", "exclude", "vocabulary", "routing", "other")
VALID_RETRIEVAL = ("invariant", "contextual")


async def relevant_memories(ctx: RunContext[ChatDeps], target_agent: str, k: int = 5) -> str:
    """
    Récupère les souvenirs destinés à ``target_agent``, les ``k`` plus proches
    sémantiquement du message utilisateur brut (``ctx.deps.message``). Vide si aucun.
    """
    return await vs.get_memories_text(target_agent, ctx.deps.user_id, query=ctx.deps.message, k=k)


async def save_memory(ctx: RunContext[ChatDeps], target_agent: str, kind: str, content: str, retrieval: str = "invariant", trigger: str | None = None, base_term: str | None = None) -> dict:
    """
    Enregistre un nouveau souvenir/correction pour l'utilisateur.
    
    À utiliser quand l'utilisateur corrige le comportement du chatbot ou ajoute
    une règle/synonyme à retenir.

    Args:
        target_agent : agent qui devra respecter ce souvenir —
            `supervisor` (délégation/routage) | `sql_research` (règles SQL) |
            `semantic_research` (recherche sémantique, exclusions, vocabulaire) |
            `conversational`.
        kind : `sql_rule` | `exclude` | `vocabulary` | `routing` | `other`.
        content : la RÈGLE / le comportement attendu, en une phrase claire, autonome
            et réutilisable (français, sans markdown). Reformule les messages
            elliptiques (« oui », « non ») à partir de l'historique.
            Pour `vocabulary` : les synonymes séparés par des virgules (ex: "lent, slow, rapide").
        retrieval : mode de récupération —
            `invariant`  = règle UNIVERSELLE, à appliquer à toute demande de cet agent
                (ex: « ne jamais mettre de point-virgule »). Toujours injectée.
            `contextual` = règle liée à une SITUATION précise (ex: « pour les tickets du
                client PTC, filtrer sur le statut X », corrections de routage). Nécessite `trigger`.
        trigger : UNIQUEMENT si `retrieval="contextual"`. La requête utilisateur
            DÉCLENCHEUSE (celle de l'historique qui a causé la correction), reformulée
            en requête autonome. Sert de clé de recherche pour retrouver la règle plus tard.
        base_term : UNIQUEMENT pour `kind=vocabulary` — le terme de base (ex: "performance").
    """
    if target_agent not in VALID_TARGET_AGENTS:
        return {"ok": False, "error": f"target_agent invalide: {target_agent}"}
    if kind not in VALID_KINDS:
        return {"ok": False, "error": f"kind invalide: {kind}"}

    # Vocabulaire : structure dédiée (global, base_term + synonymes), hors invariant/contextuel
    if kind == "vocabulary" and base_term:
        synonyms = [s.strip() for s in content.split(",") if s.strip()]
        print(f"[SAVE MEMORY] vocabulary - base_term: '{base_term}', synonyms: {synonyms}")
        await vs.add_synonyms(base_term, synonyms, ctx.deps.user_id, ctx.deps.username)
        ctx.deps.events.correction(target_agent=target_agent, kind=kind, memory=f"{base_term}: {content}")
        return {"ok": True, "target_agent": target_agent, "kind": kind}

    if retrieval not in VALID_RETRIEVAL:
        return {"ok": False, "error": f"retrieval invalide: {retrieval}"}
    if retrieval == "contextual" and not trigger:
        return {"ok": False, "error": "trigger requis pour une correction contextuelle (la requête déclencheuse)"}

    print(f"[SAVE MEMORY] target_agent={target_agent} kind={kind} retrieval={retrieval} "
          f"trigger={trigger!r} content={content!r}")
    await vs.add_memory(
        target_agent=target_agent,
        kind=kind,
        content=content,
        user_id=ctx.deps.user_id,
        retrieval=retrieval,
        trigger=trigger,
    )
    ctx.deps.events.correction(target_agent=target_agent, kind=kind, memory=content)

    return {"ok": True, "target_agent": target_agent, "kind": kind, "retrieval": retrieval}


async def delete_memory(ctx: RunContext[ChatDeps]) -> dict:
    """
    Supprime le dernier souvenir créé
    """
    print("[TOOL CALL] delete_memory")
    last_memory = await vs.get_last_memory(ctx.deps.user_id)

    if not last_memory:
        return {"ok": False, "error": "Aucun souvenir récent à supprimer."}

    print(f"Memory ID: {last_memory['id']}")
    print(f"Memory Content: {last_memory['content']}")

    try:
        await vs.delete_memory(last_memory['id'])
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
    last_memory = await vs.get_last_memory(ctx.deps.user_id)
    if not last_memory:
        return {"ok": False, "error": "Aucun souvenir récent à modifier."}
    print(f"Memory ID: {last_memory['id']}")
    print(f"Memory Content: {last_memory['content']}")
    print(f"Nouveau contenu: {new_content}")
    try:
        success = await vs.update_memory(last_memory['id'], new_content, ctx.deps.username)
        if success:
            ctx.deps.events.action("update_memory", memory_id=last_memory['id'])
            return {"ok": True, "message": "Souvenir mis à jour.", "old_content": last_memory['content'], "new_content": new_content}
        else:
            return {"ok": False, "error": "Souvenir non trouvé."}
    except Exception as e:
        return {"ok": False, "error": str(e)}