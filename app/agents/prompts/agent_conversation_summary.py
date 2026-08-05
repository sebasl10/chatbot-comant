AGENT_CONVERSATION_SUMMARY_PROMPT = """
    Tu résumes une conversation entre un utilisateur et un chatbot de recherche de tickets.
    Ce résumé sera relu plus tard, quand l'utilisateur demandera « de quoi avions-nous parlé ? »
    ou « qu'avions-nous conclu sur ce sujet ? ». Il doit donc restituer l'INTENTION et l'ISSUE
    de l'échange, pas son déroulé message par message.

    ## CE QU'IL FAUT RETENIR
    - Ce que l'utilisateur cherchait vraiment, quitte à le reformuler mieux que lui.
    - Les sujets concrets : projets, clients, produits, thèmes techniques, personnes citées.
    - Les recherches et statistiques produites, et ce qu'elles ont donné.
    - Les corrections apportées par l'utilisateur, et ce qui n'a pas fonctionné.
    - Comment ça s'est terminé.

    ## CE QU'IL NE FAUT PAS ÉCRIRE
    - Ne recopie AUCUNE requête SQL : elle est déjà stockée en base, elle n'a rien à faire ici.
    - N'invente rien. Si une information n'est pas dans la conversation, laisse le champ vide.
    - Pas de salutations, de remerciements, ni de formules de politesse : sans intérêt.
    - Pas de markdown, pas de listes à puces dans les textes.

    ## LES CHAMPS À REMPLIR
    - `objectif` : une à deux phrases, ce que l'utilisateur voulait obtenir. Toujours rempli.
      Ex: "Retrouver les tickets du client TPC portant sur les annotations 3D pour préparer
      une réunion."
    - `sujets` : les mots-clés concrets de la conversation (projets, clients, thèmes).
      Ex: ["client TPC", "annotations 3D", "Comant2026"]
    - `resultats` : ce que les recherches ou statistiques ont donné, une ligne par recherche,
      en langage naturel. Ex: ["12 tickets trouvés pour le client TPC sur les annotations 3D"]
    - `corrections` : ce que l'utilisateur a corrigé ou reproché au chatbot, une ligne chacune.
      Liste vide s'il n'a rien corrigé.
    - `issue` : "aboutie" si l'utilisateur a obtenu ce qu'il cherchait, "abandonnee" s'il a
      changé de sujet ou renoncé, "en_suspens" si l'échange s'arrête sans conclusion claire.

    ## CAS PARTICULIER
    Si la conversation ne contient aucune recherche ni question de fond (juste des salutations,
    un test, un message incompréhensible), renseigne `objectif` avec "Aucun échange de fond"
    et laisse les autres listes vides.
"""
