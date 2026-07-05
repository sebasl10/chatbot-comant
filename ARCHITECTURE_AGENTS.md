# Architecture agent du chatbot Comant

Ce document décrit la **nouvelle architecture agentique** du chatbot de recherche
de tickets : le superviseur, les agents spécialistes, les tools, les boucles
d'auto-correction, la base vectorielle Chroma et le protocole de streaming.

> **En un mot** : on est passé d'un pipeline linéaire (`if/elif` sur une intention)
> à un **superviseur** qui délègue à des **agents spécialistes**, chacun équipé
> d'**outils** (tools) qu'il appelle dans une boucle, avec **auto-correction** des
> requêtes SQL et une plus grande liberté conversationnelle.

---

## 1. Avant / Après

| | Avant | Après |
|---|---|---|
| Orchestration | `handle_stream` : chaîne `if/elif` sur l'intention | Superviseur qui **délègue** via tool calling |
| LLM | Ollama `/api/generate` (prompt + system, 1 coup) | Ollama `/v1` (OpenAI-compat) + **tool calling natif** |
| Framework | httpx maison | **Pydantic AI** (agents typés, tools, délégation, streaming) |
| Correction SQL | aucune (une requête invalide échoue) | **boucle d'auto-correction** (le modèle relit l'erreur et re-tente) |
| Recherche sémantique | table MySQL `ticket_embedding` + cosine Python | **Chroma** (collection `tickets`) |
| Mémoires/souvenirs | fichiers Markdown lus en entier | **Chroma** (collection `memories`, filtrage par métadonnées) |
| Boutons front (save/delete/affiner/corriger) | logique portée par le front | **tools** portés par le chatbot |

L'ancien pipeline reste disponible en repli (voir [§9 le flag `agent_mode`](#9-le-flag-agent_mode)).

---

## 2. Le flux d'une requête

```
Front ──POST /chat/stream──> app/routers/chat.py
                                   │ (agent_mode = True)
                                   ▼
                       app/agents/orchestrator.py : run_chat_stream()
                                   │
                                   ▼
                       app/agents/supervisor.py : supervisor_agent
                                   │  choisit UN outil de délégation
        ┌──────────────┬──────────┴───────────┬─────────────────┬──────────────┐
        ▼              ▼                      ▼                 ▼              ▼
 delegate_          delegate_            delegate_         delegate_      rename_/delete_
 conversation       new_search /         semantic_         correction      research
        │           refine_search        search              │           (tools directs)
        ▼              ▼                      ▼                 ▼
 Conversational   SQLResearchAgent      SemanticResearch   MemoryAgent
   Agent            │ tools:              Agent               │ tool:
                    │ validate_entities   │ tools:            │ save_memory
                    │ run_sql (boucle)    │ semantic_search
                    │                     │ run_sql, get_memory
                    ▼                     ▼
              persistance (create/update research) + events
                                   │
                                   ▼
       flux renvoyé : événements JSON → [STREAM_START] → texte streamé
```

**Étapes détaillées** (voir [orchestrator.py](app/agents/orchestrator.py)) :
1. Le endpoint construit un `ChatDeps` (user, historique, research_id, username).
2. `run_chat_stream` lance le superviseur en streaming.
3. Le superviseur appelle **un** outil de délégation → un agent spécialiste tourne
   (avec ses propres tools) et **accumule des événements** dans `deps.events`.
4. Avant de streamer le texte, l'orchestrateur **draine les événements** (lignes
   JSON) puis émet la sentinelle `[STREAM_START]`, puis le texte token par token.

---

## 3. Injection de dépendances : `ChatDeps`

Défini dans [app/agents/deps.py](app/agents/deps.py). Un **unique objet** circule du
superviseur → spécialistes → tools (via `RunContext.deps` de Pydantic AI). Il porte
tout l'état d'un tour de chat :

| Champ | Rôle |
|---|---|
| `user_id`, `username` | identité de l'utilisateur |
| `historique` | 10 derniers messages (contexte) |
| `research_id` | recherche courante (pour l'affinage / rename / delete) |
| `last_message_id` | id du message (persistance de l'intention, affinage) |
| `events` | **collecteur d'événements** (`EventSink`) à streamer vers le front |
| `last_sql`, `last_count` | dernière requête exécutée avec succès + son nb de résultats |
| `mode`, `previous_sql` | mode de l'agent SQL : `recherche` vs `affinage` |

`last_sql` est renseigné par le tool `run_sql` : c'est ainsi que la couche de
délégation sait **quelle requête persister**, sans confier cet effet de bord au LLM.

---

## 4. Le superviseur

[app/agents/supervisor.py](app/agents/supervisor.py). Agent **léger** dont le rôle est de
**router**. Il n'écrit pas de SQL lui-même ; il choisit un outil de délégation puis
relaie la réponse du spécialiste. Ses outils :

- `delegate_conversation` → salutations, aide, hors-périmètre, discussion libre.
- `delegate_new_search` → nouvelle recherche par filtres exacts.
- `delegate_refine_search` → affinage de la dernière recherche (part du SQL précédent).
- `delegate_semantic_search` → recherche par thème/sujet.
- `delegate_correction` → enregistrer une correction/souvenir.
- `rename_research` → **sauvegarder**/renommer la recherche courante (event `action`).
- `delete_research` → **supprimer** la recherche courante (event `action`).

Chaque `delegate_*` appelle `specialist.run(prompt, deps=ctx.deps, usage=ctx.usage)`
(pattern **agent-en-tant-que-tool** de Pydantic AI : partage des dépendances et du
compteur d'usage), puis **persiste** la recherche si un SQL valide a été produit.

---

## 5. Les agents spécialistes

Tous dans [app/agents/specialists/](app/agents/specialists/). Ce sont des `Agent`
Pydantic AI **bornés** (peu d'étapes), avec un system prompt et un sous-ensemble de tools.

### SQLResearchAgent — [sql_research.py](app/agents/specialists/sql_research.py)
Recherche par filtres exacts **et** affinage (le mode est dans `deps.mode`).
- **System prompt dynamique** : réutilise tes prompts métier existants
  (`build_recherche_prompt` / `build_affinage_prompt` → schéma live + valeurs de
  référence + règles métier + few-shot), y injecte les **souvenirs `correction_sql`**
  de l'utilisateur, et ajoute un **addendum d'utilisation des outils**.
- **Tools** : `validate_entities`, `run_sql`.
- **Méthode imposée** : valider les entités → écrire le SQL → `run_sql` →
  corriger sur erreur → répondre avec le nombre de tickets.

### SemanticResearchAgent — [semantic_research.py](app/agents/specialists/semantic_research.py)
Recherche par thème/sujet.
- **Tools** : `semantic_ticket_search` (Chroma), `get_memory`, `run_sql`.
- **Méthode** : extraire le sujet (en s'aidant des synonymes `expand_vocabulary`)
  → `semantic_ticket_search` → construire `WHERE t.id IN (...)` → exclure les
  tickets mémorisés (`exclude_ticket`) → `run_sql`.

### ConversationalAgent — [conversational.py](app/agents/specialists/conversational.py)
Salutations, aide, hors-périmètre, conversation. **Sans tool**. Réutilise le
contenu des prompts `aide` / `salutation` / `hors_perimetre` comme connaissances.

### MemoryAgent — [memory.py](app/agents/specialists/memory.py)
Enregistre les corrections. Réutilise `CORRECTION_PROMPT`, mais **appelle le tool
`save_memory`** au lieu de renvoyer du JSON.

---

## 6. Les tools (outils)

Dans [app/agents/tools/](app/agents/tools/). Ce sont des **wrappers minces** autour de
tes services existants ; les appels bloquants (MySQL, requests) sont déportés sur un
thread (`asyncio.to_thread`) pour ne pas figer le streaming.

| Tool | Fichier | Rôle | S'appuie sur |
|---|---|---|---|
| `db_schema` | [db.py](app/agents/tools/db.py) | schéma JSON de la base | `get_db_schema` |
| `run_sql` | [db.py](app/agents/tools/db.py) | **exécute** un SELECT, renvoie `{ok, count, sample}` ou `{ok:false, error}` | `execute_select` |
| `validate_entities` | [entity.py](app/agents/tools/entity.py) | valide projet/user/… contre la base (fuzzy) | `link_entities` |
| `semantic_ticket_search` | [semantic.py](app/agents/tools/semantic.py) | ids de tickets proches d'un sujet | `get_embedding` + Chroma |
| `get_memory` / `save_memory` | [memory.py](app/agents/tools/memory.py) | lire / écrire un souvenir | `vectorstore` |
| `persist_new_research` / `persist_affinage` | [research.py](app/agents/tools/research.py) | **persistance déterministe** (pas exposée au LLM) | `create_research` / `update_sql` |

> **Pourquoi la persistance n'est pas un tool du LLM ?** Créer/mettre à jour une
> recherche est un effet de bord qui doit se produire **exactement une fois**. On la
> pilote donc depuis la couche de délégation (à partir de `deps.last_sql`), pas depuis
> le modèle. En revanche `run_sql` est un tool : il est en lecture seule et peut être
> rappelé plusieurs fois (boucle d'auto-correction).

---

## 7. La boucle d'auto-correction (rétroaction)

C'est le cœur de la valeur ajoutée, **impossible avec l'ancienne architecture**.

```
        ┌────────────────────────────────────────────┐
        ▼                                            │
  le modèle écrit un SQL ──> run_sql(sql)            │
                                │                    │
                    ┌───────────┴───────────┐        │
                    ▼                       ▼        │
             {ok:true, count}        {ok:false, error}
                    │                       │        │
                    ▼                       └────────┘
        le modèle répond en français   (le modèle lit l'erreur MySQL,
        avec le nombre de tickets       corrige sa requête et rappelle
                                        run_sql — 2 corrections max)
```

Concrètement : `run_sql` **n'échoue jamais** — en cas d'erreur SQL il **renvoie**
`{"ok": false, "error": "..."}`. Le modèle voit l'erreur dans la boucle d'agent et
génère une requête corrigée. Voir [db.py](app/agents/tools/db.py).

---

## 8. La base vectorielle Chroma

[app/services/vectorstore.py](app/services/vectorstore.py). Client persistant unique
(`chroma_path`), **espace cosinus** (parité avec l'ancien `cosine_similarity`).

| Collection | Contenu | Métadonnées | Remplit |
|---|---|---|---|
| `tickets` | embeddings de tickets (réutilisés depuis MySQL, **sans recalcul**) | `ticket_id, code, type, status, priority` | `migrate_tickets_to_chroma.py` |
| `memories` | souvenirs / corrections | `type, scope (user/global), user_id, username, date` | `migrate_memories_to_chroma.py` |
| `conversation_summaries` | résumés de conversation | `user_id, conversation_id, date` | (à venir, API prête) |

**Détails importants :**
- Pour les **tickets**, on passe des embeddings **explicites** (insertion et requête)
  afin de conserver l'asymétrie d'instruction du modèle `qwen3-embedding` (la requête
  reçoit un préfixe « Instruct: », pas le document). Distance Chroma `d` → similarité
  `s = 1 - d` ; on garde les tickets `s >= seuil`.
- Pour les **mémoires/résumés**, une `OllamaEmbeddingFunction` laisse Chroma embarquer
  documents et requêtes avec le même modèle Ollama.
- `expand_vocabulary` est **global** (partagé) ; les autres types de mémoire sont
  **par utilisateur** (filtrage par métadonnées).

Scripts de vérification :
- [check_chroma_parity.py](app/scripts/check_chroma_parity.py) : compare les IDs
  Chroma vs l'ancien `search()` sur un jeu de requêtes (doivent être identiques).

---

## 9. Le protocole d'événements & le streaming

[app/services/events.py](app/services/events.py). Le front reçoit, dans l'ordre :
**lignes JSON d'événements** → sentinelle `[STREAM_START]` → **texte streamé**.

Les agents/tools n'écrivent pas sur le réseau : ils **accumulent** des événements
dans `deps.events` (`EventSink`). L'orchestrateur les draine avant `[STREAM_START]`.

| Événement | Émis par | Usage front |
|---|---|---|
| `{"event":"intention", ...}` | délégations du superviseur | compat / affichage |
| `{"event":"research", "research_id", "sql"}` | `persist_new_research` / `persist_affinage` | **redirection onglet Recherche + affichage** |
| `{"event":"action", "name":"rename_research"\|"delete_research", ...}` | tools rename/delete | **remplace les boutons** Sauvegarder/Supprimer |
| `{"event":"correction", "type", "memory"}` | tool `save_memory` | confirmation de souvenir |
| `{"event":"error", "message"}` | orchestrateur | affichage d'erreur |

L'événement `research` porte toujours `research_id` : **la redirection front existante
continue de fonctionner sans changement**.

---

## 10. Le flag `agent_mode`

[app/config.py](app/config.py) : `agent_mode` (défaut `True`).
[app/routers/chat.py](app/routers/chat.py) branche `/chat/stream` sur :
- `agent_mode = True` → nouvel orchestrateur agent ;
- `agent_mode = False` → ancien `handle_stream` (repli / A/B).

Pour revenir à l'ancien comportement sans toucher au code : `AGENT_MODE=false` dans le `.env`.

---

## 11. Arborescence des fichiers

```
app/
├── agents/                         ← NOUVEAU : la couche agent
│   ├── model.py                    modèle Ollama /v1 (Pydantic AI)
│   ├── deps.py                     ChatDeps (contexte injecté)
│   ├── orchestrator.py             run_chat_stream : streaming + events
│   ├── supervisor.py               superviseur + outils de délégation + rename/delete
│   ├── specialists/
│   │   ├── conversational.py
│   │   ├── sql_research.py         recherche + affinage (boucle run_sql)
│   │   ├── semantic_research.py    recherche par thème (Chroma)
│   │   └── memory.py               corrections/souvenirs
│   └── tools/
│       ├── db.py                   db_schema, run_sql
│       ├── entity.py               validate_entities
│       ├── semantic.py             semantic_ticket_search
│       ├── memory.py               get_memory, save_memory
│       └── research.py             persist_new_research, persist_affinage
├── services/
│   ├── vectorstore.py              ← NOUVEAU : client + collections Chroma
│   ├── events.py                   ← NOUVEAU : EventSink + [STREAM_START]
│   ├── database.py                 + rename_research / delete_research
│   ├── ollama.py                   conservé (embeddings + legacy)
│   └── router.py                   ancien pipeline (repli via agent_mode)
├── routers/chat.py                 branchement agent_mode
├── config.py                       + ollama_openai_base_url, model_ia_tools, chroma_path, agent_mode
└── scripts/
    ├── migrate_tickets_to_chroma.py
    ├── migrate_memories_to_chroma.py
    ├── check_chroma_parity.py
    ├── check_agent_ollama.py       vérifie le tool calling natif du modèle
    └── check_agent_live.py         teste une capacité de bout en bout (CLI)
```

---

## 12. Comment étendre

**Ajouter un tool à un agent** :
1. Écrire la fonction dans `app/agents/tools/…` avec la signature
   `async def mon_tool(ctx: RunContext[ChatDeps], ...) -> ...`.
2. L'enregistrer sur l'agent : `mon_agent.tool(mon_tool)`.
3. La **docstring** du tool est lue par le modèle : décris clairement quand l'utiliser.

**Ajouter un agent spécialiste** :
1. Créer `app/agents/specialists/mon_agent.py` (`Agent(get_agent_model(), deps_type=ChatDeps, ...)`).
2. Ajouter un tool `delegate_mon_agent` sur le superviseur qui appelle
   `mon_agent.run(..., deps=ctx.deps, usage=ctx.usage)`.
3. Documenter dans le system prompt du superviseur *quand* déléguer à cet agent.

**Ajouter un événement front** : ajoute une méthode sur `EventSink`
([events.py](app/services/events.py)) et émets-la depuis un tool via `ctx.deps.events`.

---

## 13. Runbook (mise en service)

```bash
pip install -r requirements.txt                       # nouvelles deps (pydantic-ai, chromadb)
python -m app.scripts.migrate_tickets_to_chroma        # migrer tickets -> Chroma
python -m app.scripts.migrate_memories_to_chroma       # migrer souvenirs -> Chroma
python -m app.scripts.check_chroma_parity              # vérifier la parité sémantique
python -m app.scripts.check_agent_ollama               # vérifier le tool calling natif
python -m app.scripts.check_agent_live 1 "cherche les tickets du projet Comant2026"
uvicorn app.main:app --reload                          # agent_mode=True par défaut
```

**Config** ([config.py](app/config.py) / `.env`) :
- `MODEL_IA_TOOLS` — modèle des agents (vide → `MODEL_IA`). Doit supporter le
  function calling (Mistral/ministral, Qwen).
- `CHROMA_PATH` — répertoire de la base vectorielle (défaut `app/chroma_db`).
- `AGENT_MODE` — `true` (nouvel agent) / `false` (ancien pipeline).

---

## 14. Points d'attention (à surveiller en live)

- **Sortie SQL brut** : les prompts `recherche`/`affinage` réutilisés se terminaient par
  « renvoie du SQL brut ». Un addendum force désormais l'appel à `run_sql`. Sur un
  modèle 14B, surveiller que le SQL n'est pas affiché tel quel ; si besoin, renforcer
  l'addendum ou retirer l'ancienne section « format de sortie ».
- **Routage du superviseur** : fiabilité du choix `delegate_*` et de la distinction
  recherche vs affinage.
- **Recherche hybride** (filtres + sémantique combinés) : pas encore recâblée dans les
  agents (l'ancien `handle_hybrid_research` existe côté legacy).
- **Front (dépôt séparé)** : retirer les 4 boutons et réagir aux events `action`.
