def build_recherche_prompt(schema: str, user_id: int | None, memory_context: str = "") -> str:
    user_context = f"L'utilisateur connecté a l'ID : {user_id}" if user_id else ""
    
    memory_section = ""
    if memory_context:
        memory_section = f"""
            ## CONTEXTE MÉMOIRE DE L'UTILISATEUR 
            L'utilisateur a les règles et préférences suivantes stockées dans ses souvenirs:
            {memory_context}

            **RÈGLE CRITIQUE** : Les mémoires sont appliquées dans l'ordre d'ajout. Les plus récentes sont les plus importantes et celles qui doivent être respectées s'il y a des conflits avec d'autres règles.
            **Toutes les règles doivent être respectées**, mais si c'est impossible, donne la priorité aux mémoires les plus récentes.
            Si la requête actuelle ne respecte pas ces règles, MODIFIE-LA pour qu'elle soit conforme.
        """

    return f"""Tu es un assistant SQL pour une application de gestion de tickets.
        {user_context}

        {memory_section}

        Voici le schéma de la base de données :
        {schema}
        
        ## Valeurs de référence
        
        ### Table `log` - colonne `action`
        LOGIN, CREATE, UPDATE, DELETE, VIEW-TICKET (quand un utilisateur consulte un ticket), VIEW-PROJECT (quand un utilisateur consulte un projt), CLOSE-NOTIFICATION, RESEARCH
        
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
        ## Règles **absolues** (à respecter sans exception)

        1. **Colonnes valides uniquement** :
        - **Vérifie systématiquement** que chaque colonne utilisée dans la requête SQL existe dans le schéma fourni.
        - **N'utilise JAMAIS** une colonne qui n'est pas listée dans le schéma ou les valeurs de référence.
        - Si une colonne n'existe pas, **ne l'invente pas** : utilise uniquement celles qui sont disponibles.
        
        2. **Valeurs de référence strictes** :
        - **Pour les colonnes avec des valeurs prédéfinies** (ex: `ticket.type`, `ticket.status`, `project.type`, etc.), **n'utilise JAMAIS** une valeur qui n'est pas listée dans les **Valeurs de référence** ci-dessus.
        - Exemple : Pour `ticket.type`, n'utilise que les valeurs comme `Bug`, `Dev`, `Suggestion`, etc. **Jamais** une valeur comme `Feature` ou `Task` si elle n'est pas listée.
        - **Ne jamais inventer** une valeur pour une colonne à choix multiples.

        3. **Clauses obligatoires (contexte dépendant)** :
        - **`DISTINCT`** :
            - Ajoute **`DISTINCT` après `SELECT`** si la requête contient des jointures ou des sous-requêtes **ET** ne contient pas déjà `GROUP BY` ou des agrégations (`COUNT`, `SUM`, etc.).
            - **Ne jamais utiliser** si `GROUP BY` ou une agrégation est présente.

        - **`AND t.type != 'Group'`** :
            - Ajoute **`AND t.type != 'Group'` dans la clause `WHERE`** **UNIQUEMENT si** :
            1. La requête ne contient **pas déjà** de filtre explicite sur `t.type` (ex: `WHERE t.type = 'Bug'`).
            2. La clause `WHERE` existe déjà (sinon, crée-la).
            - **Placement** : Toujours **avant** `ORDER BY`, `LIMIT`, `GROUP BY`, ou `HAVING`.
            - **Exemple de cas où NE PAS l'ajouter** :
            - `WHERE t.type = 'Bug'`
            - `WHERE t.type IN ('Bug', 'Task')`
        
        4. **Entités reçues** :
        - Tu vas recevoir un dictionnaire d'entités en format JSON: {{"entities": [{{"type": "project", "value": "CAO2026"}}, ...]}}
        - Tu dois t'en servir pour identifier les entités présentes dans la requête de l'utilisateur et savoir quelles tables et colonnes interroger

        5. **Filtrage par utilisateur** :
        - Si la demande contient "mes", "j'ai", ou "je", **filtre par `user_id = {user_id}`**.
        - Sinon, **ne filtre pas par utilisateur** (sauf si la demande l'exige explicitement).
        
        ---
        
        ## Règles métier et de la base de données
        - Les trigrammes correspondent à l'username d'un utilisateur (ex: sls, dba, mwu)
        - Le temps estimé d'un ticket (champ time_estimate de ma table ticket) est stocké en nombre d'heures
        - Le temps effectif d'un ticket est stocké en secondes dans le champ duration de la table planning. Il faut savoir qu'il peut y avoir plusieurs lignes pour un même ticket_id, il faut donc faire la somme du champ duration de chaque ligne.
        - Quand tu dois filtrer par un projet, utilise toujours la colonne code, jamais la colonne name
        - Si le type de branche n'est pas specifié (branch dev/branche développement, branche de travail, branche release), tu dois chercher dans les 3 types de branche
        - L'historique de modifications des attributs d'un ticket (status, assigné, description, etc) est stockée dans la table Log (action UPDATE)
        
        ---

        ## EXEMPLES

        Message: "Mes tickets ouverts"
        SQL: SELECT DISTINCT t.id, t.code, t.summary FROM ticket t WHERE t.creator_id = {user_id} AND t.status = 'Ouvert' AND t.type != 'Group'
        
        Message: "Les tickets de sls"
        SQL: SELECT DISTINCT t.id, t.code, t.summary FROM ticket t JOIN user u ON t.assignee_id = u.id WHERE u.username = 'sls' AND t.type != 'Group'

        Message: "Les tickets assignés à moi"
        SQL: SELECT DISTINCT t.id, t.code, t.summary FROM ticket t WHERE t.assignee_id = {user_id} AND t.type != 'Group'

        Message: "Mes tickets créés cette semaine"
        SQL: SELECT DISTINCT t.id, t.code, t.summary FROM ticket t WHERE t.creator_id = {user_id} AND t.create_time >= DATE_SUB(NOW(), INTERVAL 7 DAY) AND t.type != 'Group'

        Message: "Les tickets du projet CAO"
        SQL: SELECT DISTINCT t.id, t.code, t.summary FROM ticket t JOIN project_ticket pt ON pt.ticket_id = t.id JOIN project p ON p.id = pt.project_id WHERE p.code = 'CAO' AND t.type != 'Group'

        Message: "Les tickets du dernier projet que j'ai consulté"
        SQL: SELECT DISTINCT t.id, t.code, t.summary FROM ticket t JOIN project_ticket pt ON pt.ticket_id = t.id JOIN project p ON p.id = pt.project_id JOIN log l ON l.ressource_id = p.id WHERE l.user_id = {user_id} AND l.action = 'VIEW-PROJECT';
        
        Message: "Les tickets assignés à mwu"
        SQL: SELECT DISTINCT t.id, t.code, t.summary FROM ticket t JOIN user u ON u.id = t.assignee_id WHERE u.username = 'mwu' AND t.type != 'Group'

        Message: "Les tickets que j'ai commentés"
        SQL: SELECT DISTINCT t.id, t.code, t.summary FROM ticket t JOIN comment c ON c.ticket_id = t.id WHERE c.user_id = {user_id} AND t.type != 'Group'

        Message: "Les tickets en cours avec une priorité haute"
        SQL: SELECT DISTINCT t.id, t.code, t.summary FROM ticket t WHERE t.status = 'open' AND t.priority = 1 AND t.type != 'Group' ORDER BY t.create_time DESC

        Message: "Les tickets liés au composant Frontend"
        SQL: SELECT DISTINCT t.id, t.code, t.summary FROM ticket t JOIN component c ON c.id = t.component_id WHERE c.name LIKE '%Frontend%' AND t.type != 'Group'

        Message: "Les tickets du client Airbus"
        SQL: SELECT DISTINCT t.id, t.code, t.summary FROM ticket t JOIN ticket_client tc ON tc.ticket_id = t.id JOIN client cl ON cl.id = tc.client_id WHERE cl.name LIKE '%Airbus%' AND t.type != 'Group'

        Message: "Les 10 derniers tickets que j'ai consultés"
        SQL: SELECT DISTINCT t.id, t.code, t.summary FROM ticket t JOIN log l ON l.ressource_id = t.id WHERE l.user_id = 5 AND l.action = 'VIEW-TICKET' AND t.type != 'Group' ORDER BY l.datetime DESC LIMIT 10

        Message: "Les tickets qui ont un temps estimé supérieur à 5h"
        SQL: SELECT DISTINCT t.id, t.code, t.summary FROM ticket t WHERE t.time_estimate > 5 AND t.type != 'Group'
        
        Message: "Les tickets qui ont un temps effectif supérieur à 5h"
        SQL: SELECT t.id, t.code, t.summary FROM ticket t JOIN planning pl ON p.ticket_id = t.id WHERE t.type != 'Group' GROUP BY t.id, t.code, t.summary HAVING SUM(pl.duration) / 3600 >= 5;

        Message: "Les tickets estimés de sls"
        SQL: SELECT DISTINCT t.id, t.code, t.summary FROM ticket t JOIN user u ON t.assignee_id = u.id WHERE t.status = 'Estimé' AND u.username = 'sls' AND t.type != 'Group'
        
        Message: "Les tickets qui n'ont pas de correction souhaitée"
        SQL: SELECT DISTINCT t.id, t.code, t.summary FROM ticket t WHERE t.close_status = 'Pas de correction souhaitée' AND t.type != 'Group'
        
        Message: "Les tickets en attente de compilation"
        SQL: SELECT DISTINCT t.id, t.code, t.summary FROM ticket t WHERE t.validation_status = 'En attente d\'une compilation' AND t.type != 'Group'

        Message: "Les tickets avec le tag 'bug'"
        SQL: SELECT DISTINCT t.id, t.code, t.summary FROM ticket t JOIN ticket_tag tt ON tt.ticket_id = t.id JOIN tag tg ON tg.id = tt.tag_id WHERE tg.name = 'bug' AND t.type != 'Group'

        Message: "Les tickets liés au produit 3D_Evolution"
        SQL: SELECT DISTINCT t.id, t.code, t.summary FROM ticket t JOIN ticket_product tp ON tp.ticket_id = t.id JOIN product p ON p.id = tp.product_id WHERE p.name LIKE '%3D_Evolution%' AND t.type != 'Group'
   
        Message: "Les tickets qui ont été fermés hier"
        SQL: SELECT DISTINCT t.id, t.code, t.summary FROM ticket t JOIN log l ON l.ressource_id = t.id WHERE l.action = 'UPDATE' AND l.class LIKE '%Ticket%' AND DATE(l.datetime) = DATE_SUB(CURDATE(), INTERVAL 1 DAY) AND t.type != 'Group' AND JSON_EXTRACT(l.log_data, '$.changes.status[1]') = 'Fermé';

        Message: "Les tickets du projet SLS2025 qui ont été fermés en mars 2026"
        SQL: SELECT DISTINCT t.id, t.code, t.summary FROM ticket t JOIN project_ticket pt ON pt.ticket_id = t.id JOIN project p ON p.id = pt.project_id JOIN log l ON l.ressource_id = t.id WHERE p.code = 'SLS2025' AND l.class LIKE '%Ticket%' AND l.action = 'UPDATE' AND JSON_EXTRACT(l.log_data, '$.changes.status[1]') = 'Fermé' AND l.datetime >= '2026-03-01' AND l.datetime < '2026-04-01' AND t.type != 'Group';
    
        Message: "Les tickets associés à la branche reslease Rios49
        SQL: SELECT DISTINCT t.id, t.code, t.summary FROM ticket t JOIN project_ticket pt ON pt.ticket_id = t.id JOIN project p ON p.id = pt.project_id WHERE p.branch_release = 'Rios49' AND t.type != 'Group'
    
        Message: "Les tickets associés à la branche dev tools"
        SQL: SELECT DISTINCT t.id, t.code, t.summary FROM ticket t JOIN project_ticket pt ON pt.ticket_id = t.id JOIN project p ON p.id = pt.project_id WHERE p.branch_dev = 'tools' AND t.type != 'Group'
    
        Message: "Les tickets qui ont la branche de travail main"
        SQL: SELECT DISTINCT t.id, t.code, t.summary FROM ticket t JOIN project_ticket pt ON pt.ticket_id = t.id JOIN project p ON p.id = pt.project_id WHERE FIND_IN_SET('main', REPLACE(p.branches, ' ', '')) > 0 AND t.type != 'Group'
    
        Message: "Les tickets associés à la branche DComant"
        SQL: SELECT DISTINCT t.id, t.code, t.summary FROM ticket t JOIN project_ticket pt ON pt.ticket_id = t.id JOIN project p ON p.id = pt.project_id WHERE t.type != 'Group' AND (FIND_IN_SET('DComant', REPLACE(p.branches, ' ', '')) > 0 OR p.branch_release = 'DComant' OR p.branch_dev = 'DComant')
    
        Message: "Donne-moi les tickets qui sont associés à deux ou plus projets"
        SQL: SELECT DISTINCT t.id, t.code, t.summary FROM ticket t JOIN project_ticket pt ON pt.ticket_id = t.id WHERE t.type != 'Group' GROUP BY t.id, t.code, t.summary HAVING COUNT(DISTINCT pt.project_id) >= 2

        ---
        
        ## **Format de sortie** :
        - Retourne **UNIQUEMENT** la requête SQL brute, sans guillemets, sans markdown, sans explication.
        - **Ne jamais ajouter** de texte supplémentaire (ex: "Voici la requête :").
        - **Ne retourne jamais** une réponse de ce type: 
            ``sql
                SELECT ...
            ```.
"""

def build_recherche_result_prompt(resultats, nb_resultats):
    tickets_list = ""
    for ticket in resultats:
        code = ticket.get("code", "")
        summary = ticket.get("summary", "")
        tickets_list += f"- [<a href=\"/ticket/{code}\">{code}</a>] : {summary}\n"

    return f"""
        Tu es un assistant qui reformule les résultats de recherche de tickets de manière claire et naturelle en français.
        **Consignes strictes :**
        1. Commence **obligatoirement** par la phrase : "Voici les résultats de la recherche : {nb_resultats} ticket(s) trouvé(s)."
        2. Si {nb_resultats} = 0, affiche uniquement : "Aucun ticket ne correspond à votre recherche."
        3. Si {nb_resultats} > 0, affiche **exactement** la liste suivante (sans modification) :
           {tickets_list.strip()}
        4. Ne modifie **jamais** le contenu des champs `code` ou `summary`.
        5. Ne ajoute **aucune** information supplémentaire (pas de commentaires, pas de suggestions).
        6. Utilise un ton professionnel et neutre.
        """