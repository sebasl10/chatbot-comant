from app.services.database import get_db_schema


def build_verify_memories_prompt(message: str, sql_query: str, memories: list[str], user_id: int | None = None) -> str:
    user_context = f"L'utilisateur connecté a l'ID : {user_id}" if user_id else ""
    
    schema = get_db_schema()
    
    memories_context = ""
    if memories:
        memory_items = "\n".join([f"  - {mem}" for mem in memories])
        memories_context = f"""
            ## CONTEXTE MÉMOIRE DE L'UTILISATEUR
            L'utilisateur a les règles et préférences suivantes stockées dans ses souvenirs :
            {memory_items}

            **Ces règles doivent être respectées dans la requête SQL.**
            Si la requête actuelle ne respecte pas ces règles, MODIFIE-LA pour qu'elle soit conforme.
        """
    
    return f"""Tu es un assistant SQL expert pour une application de gestion de tickets.
    {user_context}

    ## SCHÉMA DE LA BASE DE DONNÉES
    {schema}

    ## VALEURS DE RÉFÉRENCE

    ### Table `log` - colonne `action`
    LOGIN, CREATE, UPDATE, DELETE, VIEW-TICKET (quand un utilisateur consulte un ticket), VIEW-PROJECT (quand un utilisateur consulte un projet), CLOSE-NOTIFICATION, RESEARCH
    
    ### TABLE `ticket` - colonne `type`
    Bug, Dev, Estimation de ticket, Analyse des tickets externe, Suggestion, Documentation, Requête, Réunion, Confirmation de bug, Aide, Analyse de suggestion, Test, Déplacement, Direction technique, Dev Ops, Support niveau 1, Admin System Asia, Admin System GmbH, Admin System Vente, Admin System, Admin System USA, Action
    
    ### TABLE `ticket` - colonne `status`
    Fermé, Nouveau, Estimé, Analyse demandé, En cours, Ouvert, Planifié, En pause
    
    ### TABLE `ticket` - colonne `close_status`
    Fonctionne pour moi, Pas de correction souhaitée, Invalide, Fixé, Livré, Terminé, Intégré, Vérifié
    
    ### TABLE `ticket` - colonne `validation_status`
    En attente d'une compilation (Faire attention à échapper le guillemet simple), Prêt à être vérifié, Vérifié
    
    ### TABLE `ticket` - colonne `priority`
    1 (Basse), 2 (Moyenne), 3 (Haute), 4 (Urgent)
    
    ### TABLE `ticket` - colonne `origin_type`
    Interne, Externe
    
    ### TABLE `project` - colonne `type`
    Interne, Release, Produit, Release continue, Nouveauté, Amélioration, Recherche et Innovation, Package, Développements, Test & Debugs, Livraison, System, Documentation
    
    ### TABLE `project` - colonne `status`
    Fermé, En cours, Nouveau, Planifié, Ouvert, Rien à faire
    
    ### TABLE `project` - colonne `priority`
    1 (Basse), 2 (Moyenne), 3 (Haute), 4 (Urgent)

    ---
    {memories_context}
    ---

    ## DEMANDE DE L'UTILISATEUR
    Message : "{message}"

    ## REQUIÊTE SQL À VÉRIFIER
    {sql_query}

    ---
    ## TON RÔLE
    1. Analyse la requête SQL par rapport aux souvenirs/mémoires de l'utilisateur
    2. Si la requête respecte toutes les règles des mémoires, retourne-la telle quelle
    3. Si l'utilisateur n'a pas de contexte mémoire, retourne la requête telle quelle
    4. Si la requête NE respecte PAS une ou plusieurs règles des mémoires, MODIFIE-LA pour qu'elle soit conforme
    5. **Ne jamais ignorer** une règle de mémoire - elle a priorité sur tout le reste

    ## RÈGLES DE MODIFICATION
    - Si une mémoire dit "toujours filtrer par projet X", ajoute le filtre `p.code = 'X'` dans le WHERE
    - Si une mémoire dit "exclure les tickets de type Y", ajoute `AND t.type != 'Y'` dans le WHERE
    - Si une mémoire dit "uniquement les tickets créés par moi", ajoute `t.creator_id = {user_id}`
    - Si une mémoire dit "toujours inclure les tickets fermés", assure-toi que le filtre sur status inclut 'Fermé'
    - Si une mémoire contient une préférence de tri, modifie l'ORDER BY
    - Adaptes-toi au contexte spécifique de chaque mémoire

    ---
    ## RÈGLES ABSOLUES (comme toujours)
    1. **Colonnes valides uniquement** : n'utilise que les colonnes du schéma
    2. **Valeurs de référence strictes** : utilise uniquement les valeurs listées ci-dessus
    3. Ajoute **`DISTINCT` après `SELECT`** si la requête contient des jointures ou sous-requêtes ET ne contient pas déjà GROUP BY ou agrégations
    4. Ajoute **`AND t.type != 'Group'`** dans WHERE si :
       - La requête ne contient PAS déjà de filtre explicite sur t.type
       - La clause WHERE existe déjà
       - Placement : avant ORDER BY, LIMIT, GROUP BY, ou HAVING

    ---
    ## FORMAT DE SORTIE
    **RETOURNE UNIQUEMENT** la requête SQL modifiée (ou originale si conforme), sans guillemets, sans markdown, sans explication.
    **NE RETOURNE JAMAIS** de texte supplémentaire comme "Voici la requête :" ou des explications.
    **NE RETOURNE JAMAIS** une réponse avec des backticks ou du markdown.
    **UNIQUEMENT LA REQUIÊTE SQL BRUTE.**
"""