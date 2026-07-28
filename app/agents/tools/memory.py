"""Tools mémoire (souvenirs / corrections), backed Chroma.

Stockage dans la collection Chroma ``memories`` (filtrage par métadonnées
``target_agent``/``kind``/``scope``/``user_id`` + recherche
sémantique).

- Lecture : ``relevant_memories(ctx, target_agent)`` récupère en top-k
  sémantique les souvenirs destinés à un agent, à partir du message utilisateur
  brut (``ctx.deps.message``).
- Écriture : ``save_memory`` (appelé par l'agent memory, qui reformule les
  messages elliptiques « oui/non » à partir de l'historique avant de stocker).

target_agent : supervisor, sql_research, semantic_research, conversational, memory.
kind         : behavior (défaut, pour tous les agents) | vocabulary (synonymes —
               valide UNIQUEMENT pour target_agent=semantic_research, seul agent
               doté d'un mécanisme de vocabulaire).
retrieval    : invariant (toujours injecté) | contextual (indexé par la requête
               déclencheuse, récupéré par similarité). Voir get_memories_text.
               L'agent memory (save_memory) n'écrit QUE du contextual ; les
               invariants ne peuvent venir que de l'endpoint /memory/add.
"""

from pydantic_ai import RunContext
from app.agents.deps import ChatDeps
from app.services import vectorstore as vs

VALID_TARGET_AGENTS = ("supervisor", "sql_research", "semantic_research", "conversational", "memory")
VALID_KINDS = ("behavior", "vocabulary")


async def relevant_memories(ctx: RunContext[ChatDeps], target_agent: str, k: int = 5) -> str:
    """
    Récupère les souvenirs destinés à ``target_agent``, les ``k`` plus proches
    sémantiquement du message utilisateur brut (``ctx.deps.message``). Vide si aucun.
    """
    # Embedding du message calculé une seule fois par tour, réutilisé par le
    # superviseur puis le spécialiste délégué (même message, même embedding).
    if ctx.deps.memory_query_embedding is None and ctx.deps.message:
        ctx.deps.memory_query_embedding = await vs.embed_memory_query(ctx.deps.message)
    # Le détail (contenu + métadonnées) est loggué dans vs.get_memories_text.
    return await vs.get_memories_text(
        target_agent,
        ctx.deps.user_id,
        query=ctx.deps.message,
        query_embedding=ctx.deps.memory_query_embedding,
        k=k,
    )


async def save_memory(
    ctx: RunContext[ChatDeps],
    target_agent: str,
    content: str,
    kind: str = "behavior",
    trigger: str | None = None,
    base_term: str | None = None,
) -> dict:
    """Enregistre un nouveau souvenir/correction pour l'utilisateur.

    À utiliser quand l'utilisateur corrige le comportement du chatbot ou ajoute
    une règle/synonyme à retenir. Le souvenir est TOUJOURS lié à la situation qui
    l'a déclenché : il faut fournir le `trigger` (sauf pour le vocabulaire).

    Args:
        target_agent: agent qui devra respecter ce souvenir.
            - `supervisor` : le chatbot a mal délégué/routé la demande (mauvais agent choisi).
              Ex: "Tu as délégué à l'agent memory, mais tu devais déléguer à l'agent semantic_search",
              "Tu as fait une recherche sémantique, mais tu devais faire une recherche par filtres".
            - `sql_research` : erreur dans la génération d'une requête SQL (filtres, colonnes, syntaxe).
              Ex: "Tu as ajouté un point-virgule à la fin de la requête SQL, ne le fais jamais",
              "Tu dois filtrer sur le status 'En attente d'une compilation', pas 'Rien à faire'".
            - `semantic_research` : erreur dans une recherche par thème/sujet (vocabulaire ou comportement).
              Ex: "Considère 'lent' et 'slow' comme synonymes de 'performance'",
              "Kinematic doit être lié à cinématique pour les recherches".
            - `conversational` : erreur de formulation ou de comportement conversationnel.
              Ex: "Tu devais répondre ma question à partir de l'historique de la conversation".
            - `memory` : erreur dans TA PROPRE classification/gestion d'un souvenir (mauvais
              `target_agent`/`kind` choisi, mauvais outil utilisé (save/update/delete), trigger
              mal reformulé). C'est une méta-correction sur ton propre comportement, pas sur un
              des 4 agents ci-dessus.
              Ex: "Tu as classé mon souvenir sur sql_research, alors qu'il fallait le mettre sur
              semantic_research", "Tu aurais dû mettre à jour mon souvenir, pas le supprimer",
              "Ce n'était pas un synonyme, ne le classe pas en vocabulary".
        content: la RÈGLE / le comportement attendu, en une phrase claire, autonome
            et réutilisable (français, sans markdown). Reformule les messages
            elliptiques (« oui », « non ») à partir de l'historique.
            Pour `kind=vocabulary` : les synonymes séparés par des virgules (ex: "lent, slow, rapide").
        kind: `behavior` (défaut — laisse cette valeur pour toute correction normale,
            quel que soit `target_agent` ; dans la quasi-totalité des cas tu n'as PAS
            besoin de fournir ce paramètre) ou `vocabulary` (synonymes — UNIQUEMENT
            valide si `target_agent="semantic_research"`).
        trigger: OBLIGATOIRE (sauf `kind=vocabulary`). La requête utilisateur
            DÉCLENCHEUSE : celle de l'historique qui a causé le comportement incorrect
            à corriger (généralement l'avant-dernier message utilisateur), reformulée
            en requête autonome et générale. Sert de clé : quand une future demande y
            ressemblera sémantiquement, la règle (`content`) sera réinjectée à l'agent
            concerné.
            Exemple : historique -> utilisateur "Cherche les tickets du client PTC" (le
            bot construit une mauvaise requête) -> utilisateur "Tu t'es trompé, tu dois
            utiliser le champ name de la table Client pour filtrer un client par son nom"
            -> `content="Pour une recherche de tickets d'un client, utiliser le champ
            name de la table Client pour filtrer par nom de client."`,
            `trigger="Cherche les tickets du client PTC"`.
        base_term: UNIQUEMENT pour `kind=vocabulary` — le terme de base auquel les
            synonymes doivent être liés (ex: "performance").
    """
    if target_agent not in VALID_TARGET_AGENTS:
        return {"ok": False, "error": f"target_agent invalide: {target_agent}"}
    if kind not in VALID_KINDS:
        return {"ok": False, "error": f"kind invalide: {kind}"}
    if kind == "vocabulary" and target_agent != "semantic_research":
        return {"ok": False, "error": "kind=vocabulary n'est valide que pour target_agent=semantic_research"}

    # Vocabulaire (semantic_research uniquement) : structure dédiée, hors trigger/retrieval
    if kind == "vocabulary":
        if not base_term:
            return {"ok": False, "error": "base_term requis pour kind=vocabulary"}
        synonyms = [s.strip() for s in content.split(",") if s.strip()]
        print(f"[SAVE MEMORY] vocabulary - base_term: '{base_term}', synonyms: {synonyms}")
        await vs.add_synonyms(base_term, synonyms, ctx.deps.user_id, ctx.deps.username)
        ctx.deps.events.correction(target_agent=target_agent, kind=kind, memory=f"{base_term}: {content}")
        return {"ok": True, "target_agent": target_agent, "kind": kind}

    # Tous les autres souvenirs écrits par l'agent sont contextuels (indexés par
    # leur déclencheur). Seul l'endpoint /memory/add peut créer des invariants.
    if not trigger:
        return {"ok": False, "error": "trigger requis (la requête utilisateur déclencheuse de la correction)"}

    print(f"[SAVE MEMORY] target_agent={target_agent} kind={kind} retrieval=contextual "
          f"trigger={trigger!r} content={content!r}")
    await vs.add_memory(
        target_agent=target_agent,
        kind=kind,
        content=content,
        user_id=ctx.deps.user_id,
        retrieval="contextual",
        trigger=trigger,
    )
    ctx.deps.events.correction(target_agent=target_agent, kind=kind, memory=content)

    return {"ok": True, "target_agent": target_agent, "kind": kind, "retrieval": "contextual"}


async def delete_memory(ctx: RunContext[ChatDeps]) -> dict:
    """Supprime le dernier souvenir créé par l'utilisateur.

    Condition : l'utilisateur doit demander EXPLICITEMENT de supprimer le
    dernier souvenir (ex: "Oublie ce que je viens de dire", "Supprime mon
    dernier souvenir"). Peut être appelé même s'il n'y a pas de souvenir créé
    dans CETTE conversation : un utilisateur peut vouloir supprimer un souvenir
    créé lors d'une autre conversation — la suppression porte sur tous les
    souvenirs de l'utilisateur, toutes conversations confondues.

    Si le résultat est {'ok': True, ...} : confirme la suppression en
    rappelant le contenu du souvenir supprimé (`content`).
    Si le résultat est {'ok': False, ...} : explique à l'utilisateur qu'il n'a
    aucun souvenir enregistré à supprimer, SANS préciser "dans cette
    conversation" (la gestion des souvenirs couvre toutes les conversations).
    """
    print("[TOOL CALL] delete_memory")
    last_memory = await vs.get_last_memory(ctx.deps.user_id)

    if not last_memory:
        return {"ok": False, "error": "Aucun souvenir récent à supprimer."}

    meta = last_memory.get("metadata") or {}
    # Règle du souvenir = la correction (contextuel) ou le document lui-même (invariant).
    rule = meta.get("correction") or last_memory["content"]
    print(f"Memory ID: {last_memory['id']} (retrieval={meta.get('retrieval')})")
    print(f"Règle: {rule}")

    try:
        await vs.delete_memory(last_memory['id'])
        ctx.deps.events.action("delete_memory", memory_id=last_memory['id'])
        return {"ok": True, "message": "Souvenir supprimé.", "content": rule}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def update_memory(ctx: RunContext[ChatDeps], new_content: str) -> dict:
    """Met à jour la RÈGLE du dernier souvenir créé par l'utilisateur.

    Condition : l'utilisateur doit demander EXPLICITEMENT de modifier le
    dernier souvenir enregistré (ex: "Corrige mon dernier souvenir pour dire
    que...", "Modifie ce que je viens de dire sur les filtres SQL"). Ne
    fonctionne que sur le dernier souvenir créé, toutes conversations
    confondues.

    `new_content` = la nouvelle règle / le nouveau comportement attendu. Le
    routage vers le bon champ est automatique : pour un souvenir contextuel, la
    requête déclencheuse (le document) reste inchangée et seule la règle
    (`metadata.correction`) est mise à jour ; pour un invariant, c'est le document.

    Après l'appel, confirme en rappelant l'ANCIEN et le NOUVEAU contenu du
    souvenir.

    Args:
        new_content: Nouvelle règle du souvenir (français, sans markdown).
    """
    print("[TOOL CALL] update_memory")
    last_memory = await vs.get_last_memory(ctx.deps.user_id)
    if not last_memory:
        return {"ok": False, "error": "Aucun souvenir récent à modifier."}

    meta = last_memory.get("metadata") or {}
    # Règle actuelle = la correction (contextuel) ou le document lui-même (invariant).
    old_rule = meta.get("correction") or last_memory["content"]
    print(f"Memory ID: {last_memory['id']} (retrieval={meta.get('retrieval')})")
    print(f"Ancienne règle: {old_rule}")
    print(f"Nouvelle règle: {new_content}")
    try:
        success = await vs.update_memory(last_memory['id'], content=new_content)
        if success:
            ctx.deps.events.action("update_memory", memory_id=last_memory['id'])
            return {"ok": True, "message": "Souvenir mis à jour.", "old_content": old_rule, "new_content": new_content}
        else:
            return {"ok": False, "error": "Souvenir non trouvé."}
    except Exception as e:
        return {"ok": False, "error": str(e)}