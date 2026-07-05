# Tests à réaliser — branche `feature/langchain-architecture`

> À exécuter sur la machine disposant des accès **Ollama + MySQL + `.env`**.
> Aucun de ces tests n'a été lancé pendant l'implémentation (machine sans LLM/DB).
> Seuls des contrôles d'import/compilation ont été faits.

Prérequis :
- Ollama lancé (`ollama serve`) avec le modèle de tool calling (`ministral-3:14b` ou
  un modèle Mistral/Qwen tool-capable) et le modèle d'embeddings (`qwen3-embedding:4b`).
- MySQL de l'application accessible.
- `.env` renseigné (voir variables ci-dessous).
- Environnement Python : `pip install -r requirements.txt`.

Variables `.env` utiles (nouvelles / à vérifier) :
```
OLLAMA_BASE_URL=http://localhost:11434     # racine Ollama (SANS /v1 ni /api) — utilisé par ChatOllama
MODEL_IA=ministral-3:14b
MODEL_IA_TOOLS=                             # vide => MODEL_IA ; sinon un modèle tool-capable
MODEL_IA_EMBEDDING=qwen3-embedding:4b
CHROMA_PATH=app/chroma_db                   # base vectorielle
AGENT_MODE=true                             # true = nouvel agent LangGraph ; false = ancien pipeline
```

---

## 0. Install & sanity (sans LLM/DB)

```bash
pip install -r requirements.txt
python -c "import app.main; print('app.main OK')"
```
**Attendu** : import sans erreur. (Vérifie que langchain/langgraph/langchain-ollama
s'installent bien sur ta version de Python.)

---

## 1. Tool calling natif (Ollama requis)

```bash
python -m app.scripts.check_agent_ollama
```
**Attendu** : `✅ TOOL CALLING NATIF OK` et la ligne `[tool get_weather appelé] ville=Toulouse`.
**Si échec** (`⚠️ … n'a PAS appelé le tool`) : mets `MODEL_IA_TOOLS` sur un modèle
tool-capable (ex. `qwen2.5:14b`) et relance.

---

## 2. Migrations Chroma (MySQL + Ollama requis)

```bash
python -m app.scripts.migrate_tickets_to_chroma     # réutilise les embeddings existants (pas de recalcul)
python -m app.scripts.migrate_memories_to_chroma    # parse app/memory/**.md -> Chroma
python -m app.scripts.check_chroma_parity           # compare Chroma vs ancien search()
```
**Attendu** :
- migrations : `✅ Migration terminée : N … dans la collection …`.
- parité : `✅ Parité parfaite.` (sinon, la liste des tickets divergents s'affiche).

---

## 3. Test par capacité (Ollama + MySQL requis)

Le script `check_agent_live` exécute l'orchestrateur exactement comme l'endpoint et
affiche le flux : lignes d'événements JSON, puis `[STREAM_START]`, puis la réponse.

Remplace `1` par un `user_id` réel et adapte les noms (projet, etc.) à ta base.

### 3.1 Conversation
```bash
python -m app.scripts.check_agent_live 1 "bonjour, que peux-tu faire ?"
```
**Attendu** : event `{"event":"intention","intention":"conversation"}` puis une réponse
naturelle décrivant les capacités. **Aucun** event `research`.

### 3.2 Recherche (filtres exacts)
```bash
python -m app.scripts.check_agent_live 1 "cherche les tickets du projet Comant2026 créés par <trigramme>"
```
**Attendu** : events `intention=recherche` **et**
`{"event":"research","research_id":<id>,"sql":"SELECT …"}`, puis « J'ai trouvé N tickets ».
Vérifie en base qu'une ligne `research` a été créée avec ce SQL.

### 3.3 Affinage
Enchaîne après 3.2 en passant le `research_id` obtenu (3e argument) :
```bash
python -m app.scripts.check_agent_live 1 "garde seulement ceux qui sont ouverts" <research_id>
```
**Attendu** : `intention=affinage` + event `research` avec **le même** `research_id`
(le SQL est mis à jour, pas recréé).

### 3.4 Recherche sémantique
```bash
python -m app.scripts.check_agent_live 1 "les tickets qui parlent de cinématique"
```
**Attendu** : `intention=recherche_semantique` + event `research` ; le SQL contient
`WHERE t.id IN (…)`.

### 3.5 Correction / mémoire
```bash
python -m app.scripts.check_agent_live 1 "quand je parle de cinématique, inclus aussi vitesse de rotation"
```
**Attendu** : event `{"event":"correction","type":"expand_vocabulary","memory":"…"}`
et confirmation. Vérifie que le souvenir est bien ajouté dans la collection Chroma `memories`.

### 3.6 Sauvegarder (rename) — remplace le bouton « Sauvegarder »
```bash
python -m app.scripts.check_agent_live 1 "sauvegarde cette recherche sous le nom Bugs Comant" <research_id>
```
**Attendu** : event `{"event":"action","name":"rename_research","research_id":<id>,"new_name":"Bugs Comant"}`.
Vérifie le nouveau nom en base.

### 3.7 Supprimer (delete) — remplace le bouton « Supprimer »
```bash
python -m app.scripts.check_agent_live 1 "supprime cette recherche" <research_id>
```
**Attendu** : event `{"event":"action","name":"delete_research","research_id":<id>}`.
Vérifie la suppression en base.

---

## 4. Boucle d'auto-correction SQL

But : vérifier que sur une erreur SQL, l'agent **re-tente** au lieu d'échouer.

Option simple : pose une demande qui pousse le modèle vers une colonne/table ambiguë,
et observe les logs — le tool `run_sql` doit renvoyer `{"ok": false, "error": …}` puis
un second appel `run_sql` corrigé.

Option ciblée (forcer l'erreur) : dans [app/agents/tools/db.py](app/agents/tools/db.py),
fais temporairement lever une erreur au 1er appel de `execute_select`, et vérifie que
l'agent relit l'erreur et rappelle `run_sql`. **Attendu** : la réponse finale aboutit
malgré la 1re erreur (≤ 2 corrections).

---

## 5. Parité front (comparaison avec la branche Pydantic AI)

Le contrat de streaming doit être **identique** entre les deux branches :
- mêmes **clés JSON** d'événements (`intention`, `research` avec `research_id`+`sql`,
  `action` avec `name`, `correction`), 
- même **ordre** : toutes les lignes d'événements **avant** `[STREAM_START]`, puis le texte.

Test : lance la même requête (ex. 3.2) sur les deux branches et compare la partie
« header » (avant `[STREAM_START]`). Le front ne doit pas voir de différence :
la redirection vers l'onglet Recherche (via `research_id`) et la réaction aux events
`action` (rename/delete) doivent fonctionner à l'identique.

---

## 6. End-to-end via l'API

```bash
uvicorn app.main:app --reload
```
Puis, depuis le front (ou curl) :
```bash
curl -N -X POST http://localhost:8000/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"message":"cherche les tickets du projet Comant2026","model":"ministral-3:14b","user_id":1,"historique":[],"last_message_id":0,"intention":"","research_id":0}'
```
**Attendu** : le flux `événements JSON → [STREAM_START] → texte`. Le front doit
rediriger vers l'onglet Recherche grâce au `research_id`.

Repli immédiat vers l'ancien pipeline : mettre `AGENT_MODE=false` dans `.env`.

---

## 7. Points à surveiller (spécifiques LangChain)

- **`OLLAMA_BASE_URL`** doit être la **racine** (`http://localhost:11434`), pas
  `.../api/generate` : `ChatOllama` utilise l'API native `/api/chat`.
- **Sortie SQL brut** : si le modèle affiche parfois le SQL au lieu d'appeler `run_sql`,
  renforcer l'addendum d'outils dans [sql_research.py](app/agents/specialists/sql_research.py).
- **Streaming** : l'orchestrateur streame la réponse **mot à mot** après complétion
  (`ainvoke`), pas token par token. Si tu veux du token-level, il faudra filtrer les
  chunks du superviseur via `astream(stream_mode="messages")` (délicat avec sous-agents).
- **Compat versions** : `langchain>=1.0`, `langgraph>=1.0`, `langchain-ollama>=1.0`
  (API `create_agent` de `langchain.agents`).
