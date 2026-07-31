"""
Tools mémoire (souvenirs / corrections), backed Chroma.
"""

from pydantic_ai import RunContext

from app.agents.deps import ChatDeps
from app.agents.specialists.memory_judge import judge_candidates
from app.services import vectorstore as vs

VALID_TARGET_AGENTS = (
    "supervisor",
    "sql_research",
    "semantic_research",
    "statistics",
    "conversational",
    "memory",
)
VALID_KINDS = ("behavior", "vocabulary")


async def relevant_memories(ctx: RunContext[ChatDeps], target_agent: str, k: int = 5) -> str:
    """
    Récupère les souvenirs destinés à ``target_agent``, les ``k`` plus proches
    sémantiquement du message utilisateur brut (``ctx.deps.message``). Vide si aucun.
    """
    if ctx.deps.memory_query_embedding is None and ctx.deps.message:
        ctx.deps.memory_query_embedding = await vs.embed_memory_query(ctx.deps.message)
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
    """
    Enregistre un nouveau souvenir/correction pour l'utilisateur.

    À utiliser quand l'utilisateur corrige le comportement du chatbot ou ajoute
    une règle/synonyme à retenir. Le souvenir est TOUJOURS lié à la situation qui
    l'a déclenché : il faut fournir le `trigger` (sauf pour le vocabulaire).

    Args:
        target_agent: agent qui devra respecter ce souvenir.
            - `supervisor` : le chatbot a mal délégué/routé la demande (mauvais agent choisi ou mauvaise fonctionnaliée identifiée).
              Ex: "Tu as délégué à l'agent memory, mais tu devais déléguer à l'agent semantic_search",
              "Tu as fait une recherche sémantique, mais tu devais faire une recherche par filtres".
            - `sql_research` : erreur dans la génération d'une requête SQL (filtres, colonnes, syntaxe).
              Ex: "Tu as ajouté un point-virgule à la fin de la requête SQL, ne le fais jamais",
              "Tu dois filtrer sur le status 'En attente d'une compilation', pas 'Rien à faire'".
            - `semantic_research` : erreur dans une recherche par thème/sujet (vocabulaire ou comportement).
              Ex: "Considère 'lent' et 'slow' comme synonymes de 'performance'",
              "Kinematic doit être lié à cinématique pour les recherches".
            - `statistics` : erreur dans le calcul d'un indicateur agrégé (mauvais regroupement,
              mauvaise règle de calcul du temps, mauvaise catégorie R&D/absence, double comptage).
              Ex: "Le temps effectif par salarié doit se baser sur planning.user_id, pas sur
              l'assigné du ticket", "Une estimation est correcte à 20 % près, pas 10 %".
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
            *Dans ce cas, ne rajoute JAMAIS de texte additionel. Utilise uniquement les termes qui du message de
            l'utilisateur, ne'ajoute pas des termes que tu trouves dans l'historique et n'invente pas d'autres mots*
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

    Returns:
        Avant confirmation, base-toi TOUJOURS sur `action` (et `message`) plutôt
        que de supposer qu'un nouveau souvenir a été créé :
        - `action="created"` : nouveau souvenir enregistré normalement.
        - `action="duplicate"` : rien enregistré, une règle équivalente existait déjà
          (`existing_content`). Dis-le à l'utilisateur au lieu de confirmer une création.
        - `action="merged"` : fusionné avec une règle existante proche (`content` =
          la règle fusionnée). Confirme avec cette règle fusionnée, pas la tienne seule.
        - `action="replaced"` : une règle CONTRADICTOIRE existait (`previous_content`) et
          a été automatiquement remplacée par la nouvelle (`content`). Mentionne le
          remplacement dans ta confirmation (ex: "j'ai remplacé la règle sur X par Y").

        Pour `kind=vocabulary`, pas de champ `action`, regarde plutôt :
        - `added` : les termes réellement nouveaux, effectivement ajoutés.
        - `already_existing` (optionnel) : termes déjà synonymes de CE `base_term`
          — PAS ré-ajoutés. Dis à l'utilisateur qu'ils l'étaient déjà, et confirme
          uniquement l'ajout des termes de `added`.
    """
    if target_agent not in VALID_TARGET_AGENTS:
        return {"ok": False, "error": f"target_agent invalide: {target_agent}"}
    if kind not in VALID_KINDS:
        return {"ok": False, "error": f"kind invalide: {kind}"}
    if kind == "vocabulary" and target_agent != "semantic_research":
        return {
            "ok": False,
            "error": "kind=vocabulary n'est valide que pour target_agent=semantic_research",
        }

    # Vocabulaire (semantic_research uniquement)
    if kind == "vocabulary":
        if not base_term:
            return {"ok": False, "error": "base_term requis pour kind=vocabulary"}
        synonyms = [s.strip() for s in content.split(",") if s.strip()]
        print(f"[SAVE MEMORY] vocabulary - base_term: '{base_term}', synonyms: {synonyms}")
        existing_synonyms = {
            s.lower() for s in (await vs.get_vocabulary_for_term(base_term))["synonyms"]
        }
        already_existing = [s for s in synonyms if s.lower() in existing_synonyms]
        new_terms = [s for s in synonyms if s.lower() not in existing_synonyms]

        if new_terms:
            await vs.add_synonyms(base_term, new_terms, ctx.deps.user_id, ctx.deps.username)
            ctx.deps.events.correction(
                target_agent=target_agent, kind=kind, memory=f"{base_term}: {', '.join(new_terms)}"
            )

        result = {
            "ok": True,
            "target_agent": target_agent,
            "kind": kind,
            "base_term": base_term,
            "added": new_terms,
        }
        if already_existing:
            result["already_existing"] = already_existing
        return result

    if not trigger:
        return {
            "ok": False,
            "error": "trigger requis (la requête utilisateur déclencheuse de la correction)",
        }

    print(
        f"[SAVE MEMORY] target_agent={target_agent} kind={kind} retrieval=contextual "
        f"trigger={trigger!r} content={content!r}"
    )

    # Avant de créer un nouveau souvenir, on cherche des candidats proches déjà stockés et on les fait
    # classer par un juge (duplicate/conflict/complement/unrelated).

    chosen_candidate, chosen_verdict = None, None
    try:
        trigger_embedding = await vs.embed_memory_query(trigger)
        candidates = await vs.find_similar_contextual_memories(
            target_agent, ctx.deps.user_id, trigger_embedding
        )
        if candidates:
            verdicts = {
                v.candidate_id: v for v in await judge_candidates(trigger, content, candidates)
            }
            for candidate in candidates:
                verdict = verdicts.get(candidate["id"])
                if verdict and verdict.relation != "unrelated":
                    chosen_candidate, chosen_verdict = candidate, verdict
                    break
    except Exception as e:
        print(f"[MEMORY RECONCILE] échec du juge, écriture normale : {e}")

    if chosen_verdict and chosen_verdict.relation == "duplicate":
        print(f"[MEMORY RECONCILE] duplicate de {chosen_candidate['id']!r}, rien écrit")
        return {
            "ok": True,
            "target_agent": target_agent,
            "kind": kind,
            "action": "duplicate",
            "message": "Ce souvenir existe déjà, aucune nouvelle règle ajoutée.",
            "existing_content": chosen_candidate["rule"],
        }

    if chosen_verdict and chosen_verdict.relation == "complement":
        merged = chosen_verdict.merged_content or content
        await vs.update_memory(chosen_candidate["id"], content=merged)
        print(f"[MEMORY RECONCILE] fusion avec {chosen_candidate['id']!r}: {merged!r}")
        ctx.deps.events.correction(target_agent=target_agent, kind=kind, memory=merged)
        return {
            "ok": True,
            "target_agent": target_agent,
            "kind": kind,
            "action": "merged",
            "message": "Souvenir fusionné avec une règle existante proche.",
            "content": merged,
        }

    if chosen_verdict and chosen_verdict.relation == "conflict":
        new_id = await vs.add_memory(
            target_agent=target_agent,
            kind=kind,
            content=content,
            user_id=ctx.deps.user_id,
            retrieval="contextual",
            trigger=trigger,
        )
        await vs.supersede_memory(chosen_candidate["id"], new_id, content, ctx.deps.username)
        print(f"[MEMORY RECONCILE] conflit : {chosen_candidate['id']!r} remplacé par {new_id!r}")
        ctx.deps.events.correction(target_agent=target_agent, kind=kind, memory=content)
        return {
            "ok": True,
            "target_agent": target_agent,
            "kind": kind,
            "action": "replaced",
            "message": "Une règle contradictoire existait : elle a été remplacée par la nouvelle.",
            "previous_content": chosen_candidate["rule"],
            "content": content,
        }

    await vs.add_memory(
        target_agent=target_agent,
        kind=kind,
        content=content,
        user_id=ctx.deps.user_id,
        retrieval="contextual",
        trigger=trigger,
    )
    ctx.deps.events.correction(target_agent=target_agent, kind=kind, memory=content)

    return {
        "ok": True,
        "target_agent": target_agent,
        "kind": kind,
        "retrieval": "contextual",
        "action": "created",
    }


async def delete_memory(ctx: RunContext[ChatDeps]) -> dict:
    """
    Supprime le dernier souvenir créé par l'utilisateur.

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
        await vs.delete_memory(last_memory["id"])
        ctx.deps.events.action("delete_memory", memory_id=last_memory["id"])
        return {"ok": True, "message": "Souvenir supprimé.", "content": rule}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def update_memory(ctx: RunContext[ChatDeps], new_content: str) -> dict:
    """
    Met à jour la RÈGLE du dernier souvenir créé par l'utilisateur.

    Condition : l'utilisateur doit demander EXPLICITEMENT de modifier le
    dernier souvenir enregistré (ex: "Corrige mon dernier souvenir pour dire
    que...", "Modifie ce que je viens de dire sur les filtres SQL"). Ne
    fonctionne que sur le dernier souvenir créé, toutes conversations
    confondues.

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
        success = await vs.update_memory(last_memory["id"], content=new_content)
        if success:
            ctx.deps.events.action("update_memory", memory_id=last_memory["id"])
            return {
                "ok": True,
                "message": "Souvenir mis à jour.",
                "old_content": old_rule,
                "new_content": new_content,
            }
        else:
            return {"ok": False, "error": "Souvenir non trouvé."}
    except Exception as e:
        return {"ok": False, "error": str(e)}
