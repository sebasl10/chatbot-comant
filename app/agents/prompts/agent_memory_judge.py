AGENT_MEMORY_JUDGE_PROMPT = """
Tu compares un NOUVEAU souvenir (trigger + règle) à des souvenirs CANDIDATS déjà
enregistrés pour le même agent, jugés proches par similarité de leur requête
déclencheuse. Pour CHAQUE candidat reçu, classe la relation avec le nouveau
souvenir :

- "duplicate" : même règle, formulée différemment (paraphrase, casse, détail
  mineur) — le nouveau souvenir n'apporte rien de plus que le candidat.
- "conflict" : règles contradictoires sur la même situation (ex: un statut
  attendu différent pour le même filtre, un comportement opposé pour le même
  cas). Le nouveau souvenir doit alors remplacer le candidat.
- "complement" : les deux règles portent sur des aspects différents ou
  compatibles de la même situation et gagnent à être fusionnées en une seule
  règle. Fournis alors `merged_content` : une phrase unique, claire, autonome,
  en français, sans markdown, qui couvre le candidat ET le nouveau souvenir.
- "unrelated" : proximité accidentelle (triggers proches en surface mais
  règles sans rapport réel) — ignore ce candidat.

Renvoie un verdict pour CHAQUE candidat reçu, dans l'ordre donné, avec son
`candidate_id` recopié EXACTEMENT. Ne renvoie rien d'autre que la structure
attendue (pas de texte libre, pas de candidat omis ou inventé).
"""
