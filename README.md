# Chatbot API Comant - Système de Gestion Intelligente de Tickets

> **Version 0.1.0** - Une API FastAPI pour la recherche et la gestion de tickets via un chatbot IA

---

## 📋 Table des Matières

- [📌 À Propos](#-à-propos)
- [🏗️ Architecture](#️-architecture)
- [✨ Fonctionnalités Principales](#-fonctionnalités-principales)
- [🎯 Classification des Intentions](#-classification-des-intentions)
- [🔍 Types de Recherche](#-types-de-recherche)
- [🔌 API Endpoints](#-api-endpoints)
- [⚙️ Configuration](#️-configuration)
- [🚀 Installation et Exécution](#-installation-et-exécution)
- [🧪 Tests](#-tests)
- [📁 Structure du Projet](#-structure-du-projet)
- [📊 Exemples d'Utilisation](#-exemples-dutilisation)
- [🔄 Fine-Tuning et Export](#-fine-tuning-et-export)

---

## 📌 À Propos

**Chatbot API Comant** est une application FastAPI conçue pour fournir une interface de chat intelligente pour la gestion et la recherche de tickets dans une base de données Comant. L'application utilise des modèles de langage (LLM) locaux via **Ollama** ou **LMStudio** pour comprendre les requêtes en langage naturel, les classer par intention, extraire les entités, générer des requêtes SQL, et retourner des résultats pertinents.

### Cas d'Usage Principaux

- ✅ Recherche de tickets par critères structurés (projet, statut, assigné, etc.)
- ✅ Recherche sémantique par thème ou sujet
- ✅ Recherche hybride combinant filtres et thèmes
- ✅ Affinage interactif des requêtes
- ✅ Gestion des conversations avec historique
- ✅ Export de données pour le fine-tuning des modèles
- ✅ Intégration avec une base de données MySQL


---

## 🏗️ Architecture

```
chatbot-api/
├── app/
│   ├── main.py                 # Point d'entrée FastAPI
│   ├── config.py               # Configuration (variables d'environnement)
│   ├── models/
│   │   └── chat.py             # Schémas Pydantic (ChatRequest, NameRequest)
│   ├── routers/
│   │   ├── chat.py             # Endpoints de chat (streaming)
│   │   ├── name.py             # Génération de noms de conversation
│   │   └── admin.py            # Endpoints administrateurs (export)
│   ├── services/
│   │   ├── router.py           # Service principal de routage des requêtes
│   │   ├── ollama.py           # Intégration avec Ollama API
│   │   ├── database.py         # Connexion et requêtes MySQL
│   │   ├── embedding.py        # Recherche sémantique via embeddings
│   │   ├── embedding_generation.py # Génération d'embeddings pour les tickets
│   │   ├── intention.py        # Classification des intentions
│   │   ├── entity_cache.py     # Cache et validation des entités
│   │   ├── conversation_name.py # Génération de noms de conversation
│   │   └── finetuning_couples.py # Export pour fine-tuning (SFT/DPO)
│   ├── prompts/
│   │   ├── intention.py        # Prompt pour la classification d'intentions
│   │   ├── recherche.py        # Prompt pour la génération SQL
│   │   ├── affinage.py         # Prompt pour l'affinage de requêtes
│   │   ├── hybrid_research.py  # Prompts pour la recherche hybride
│   │   ├── entity_extraction.py # Prompt pour l'extraction d'entités
│   │   ├── recherche_semantique_text.py # Prompt de nettoyage texte
│   │   ├── conversation_name.py # Prompt de nommage
│   │   ├── aide.py             # Prompt d'aide
│   │   ├── salutation.py       # Prompt de salutation
│   │   └── hors_perimetre.py    # Prompt hors périmètre
│   └── tests/
│       └── tests.py            # Tests automatisés (SQL, intentions)
├── exports/                    # Dossier d'export des données
│   ├── sft/                    # Fichiers SFT (Supervised Fine-Tuning)
│   └── dpo/                    # Fichiers DPO (Direct Preference Optimization)
├── Modelfiles/                 # Fichiers de configuration de modèles
├── .env                       # Variables d'environnement
├── .gitignore
├── README.md
├── requirements.txt
└── prompt_recherche.txt        # Documentation des prompts
```

### Stack Technique

| Composant | Technologie | Version |
|-----------|-------------|---------|
| **Framework Web** | FastAPI | >= 0.95.0 |
| **Serveur ASGI** | Uvicorn | >= 0.21.0 |
| **Configuration** | Pydantic Settings | >= 2.0.0 |
| **Client HTTP** | HTTPX | >= 0.24.0 |
| **Base de données** | MySQL | 5.7+ |
| **ORM** | PyMySQL | Latest |
| **IA Locale** | Ollama / LMStudio | - |
| **Embeddings** | NumPy, Requests | Latest |
| **Fuzzy Matching** | RapidFuzz | Latest |
| **HTML Parsing** | BeautifulSoup4 | Latest |

---

## ✨ Fonctionnalités Principales

### 1. **Chat en Temps Réel avec Streaming**

- Communication bidirectionnelle via WebSocket-like streaming
- Réponses progressives mot par mot
- Gestion de l'historique des conversations
- Persistance des intentions et requêtes

### 2. **Classification Automatique des Intentions**

Le système identifie automatiquement le type de requête parmi 8 catégories :
- `salutation` - Messages de politesse
- `aide` - Demandes d'aide ou d'information
- `recherche` - Recherche par critères structurés
- `recherche_semantique` - Recherche par thème
- `recherche_hybride` - Combinaison filtres + thème
- `affinage` - Précision/correction de recherche
- `hors_perimetre` - Requêtes hors scope
- `incomprehensible` - Messages non exploitables

### 3. **Recherche Intelligente de Tickets**

Trois modes de recherche disponibles :

#### 🎯 Recherche Structurée (`recherche`)
Recherche par critères explicites :
- Projet, statut, priorité
- Assigné à, créé par
- Date, client, produit, composant
- Tags, type, etc.

**Exemple :** "Mes tickets ouverts du projet CAO créés cette semaine"

#### 🔍 Recherche Sémantique (`recherche_semantique`)
Recherche par similitude de contenu :
- Utilisation d'embeddings vectoriels
- Comparaison de similarité cosinus
- Modèle : `qwen3-embedding:4b`

**Exemple :** "Tickets qui parlent de cinématique"

#### 🔄 Recherche Hybride (`recherche_hybride`)
Combinaison des deux approches :
- Décomposition de la requête en filtres + thème
- Exécution séparée des deux recherches
- Fusion intelligente des résultats SQL

**Exemple :** "Tickets du projet Comant2026 qui parlent de cinématique"

### 4. **Extraction et Validation d'Entités**

- Identification automatique des entités dans les requêtes
- Validation contre la base de données
- Suggestions de correction (fuzzy matching)
- Cache des entités pour performances

**Entités gérées :**
- Projet, client, produit, composant
- Utilisateur, tag
- Branches (dev, travail, release)

### 5. **Affinage de Recherche**

Permet de préciser une recherche existante :
- "Seulement les fermés"
- "Plutôt ce mois-ci"
- "Filtre par projet CAO"

### 6. **Génération de Noms de Conversation**

Création automatique de noms descriptifs basés sur l'historique.

### 7. **Fine-Tuning et Export de Données**

- Export des couples (requête → SQL) pour SFT
- Export des triplets (requête → SQL incorrect → SQL correct) pour DPO
- Format ShareGPT JSONL
- Utilisation des feedbacks utilisateurs

### 8. **Base de Données MySQL**

- Schéma dynamique détecté automatiquement
- Exécution sécurisée de requêtes SELECT
- Journalisation des recherches
- Gestion des utilisateurs, tickets, projets, etc.

---

## 🎯 Classification des Intentions

Le système utilise un prompt détaillé pour classer chaque message utilisateur. Voici les critères :

| Intention | Description | Exemples |
|-----------|-------------|----------|
| `salutation` | Messages de politesse | "Bonjour", "Merci", "Bonne journée" |
| `aide` | Demande d'aide | "Tu peux faire quoi ?", "Comment ça marche ?" |
| `recherche` | Critères structurés | "Mes tickets ouverts", "Tickets du projet CAO" |
| `recherche_semantique` | Thème sémantique | "Tickets qui parlent de cinématique" |
| `recherche_hybride` | Filtres + thème | "Tickets du projet CAO qui parlent de bugs" |
| `affinage` | Précision de recherche | "Seulement les fermés", "Et ceux de cette semaine" |
| `hors_perimetre` | Hors scope | "Quel temps fait-il ?", "Écris-moi un email" |
| `incomprehensible` | Incompréhensible | "???", "azdaz", "ok" |

**Règles de discrimination :**
- `recherche` : uniquement des critères structurés
- `recherche_semantique` : uniquement un thème (mots-clés : parlent de, sur, concernent)
- `recherche_hybride` : au moins un filtre ET un thème

---

## 🔍 Types de Recherche

### 1. Recherche Structurée

**Processus :**
1. Extraction des entités (projet, statut, utilisateur, etc.)
2. Validation des entités contre la base
3. Génération de la requête SQL
4. Exécution et retour des résultats

**Exemple de requête SQL générée :**
```sql
SELECT DISTINCT t.id, t.code, t.summary 
FROM ticket t 
JOIN project_ticket pt ON pt.ticket_id = t.id 
JOIN project p ON p.id = pt.project_id 
WHERE p.code = 'CAO' 
  AND t.status = 'Ouvert' 
  AND t.assignee_id = 5 
  AND t.type != 'Group'
```

### 2. Recherche Sémantique

**Processus :**
1. Nettoyage de la requête utilisateur
2. Génération de l'embedding vectoriel
3. Comparaison avec les embeddings des tickets
4. Filtrage par seuil de similarité (default: 0.5)
5. Retour des tickets les plus pertinents

**Modèle d'embedding :** `qwen3-embedding:4b` (4096 dimensions)

### 3. Recherche Hybride

**Processus :**
1. Décomposition de la requête en deux parties :
   - Requête de filtres (critères structurés)
   - Requête sémantique (thème)
2. Exécution séparée des deux recherches
3. Génération d'une requête SQL finale combinant les résultats
4. Exécution et retour

**Exemple de décomposition :**
- Input: "Tickets du projet CAO qui parlent de cinématique"
- Filtres: "Les tickets du projet CAO"
- Sémantique: "Les tickets qui parlent de cinématique"
- SQL final: Combinaison intelligente des deux requêtes

---

## 🔌 API Endpoints

### Base URL
```
http://localhost:8000
```

### Endpoints Disponibles

#### 💬 **Chat**

| Méthode | Endpoint | Description | Paramètres |
|---------|----------|-------------|------------|
| POST | `/chat/stream` | Chat en streaming | `ChatRequest` |

**ChatRequest Schema :**
```json
{
  "message": "string",           // Message utilisateur
  "model": "string",             // Modèle IA (default: settings.model_ia)
  "user_id": "integer",          // ID utilisateur
  "historique": "array",         // Historique de la conversation
  "last_message_id": "integer",   // ID du dernier message
  "intention": "string",         // Intention (optionnel, calculée si vide)
  "research_id": "integer"       // ID de recherche pour affinage
}
```

**Réponse (Streaming) :**
```
[STREAM_START]\n
{
  "intention": "recherche",
  "generated_sql": "SELECT ...",
  "research_id": 123,
  "vocabularyError": null
}

<p>Résultats de la recherche : 5 tickets trouvés.</p>
<Ticket 1>
<Ticket 2>
...
```

#### 📝 **Noms de Conversation**

| Méthode | Endpoint | Description | Paramètres |
|---------|----------|-------------|------------|
| POST | `/name/create` | Génère un nom de conversation | `NameRequest` |

**NameRequest Schema :**
```json
{
  "historique": "array",           // Historique des messages
  "conversation_id": "integer"    // ID de la conversation
}
```

**Réponse :**
```json
{
  "name": "Recherche de tickets du projet CAO"
}
```

#### 📊 **Health Check**

| Méthode | Endpoint | Description |
|---------|----------|-------------|
| GET | `/` | Message de bienvenue |
| GET | `/health` | Statut de l'API |

**Réponses :**
```json
// GET /
{"message": "Bienvenue dans ton application FastAPI !"}

// GET /health
{"status": "ok"}
```

#### 🧪 **Tests**

| Méthode | Endpoint | Description |
|---------|----------|-------------|
| GET | `/tests` | Exécute les tests d'intentions |
| GET | `/tests/tokens` | Teste le comptage de tokens |

#### 📥 **Export (Admin)**

| Méthode | Endpoint | Description |
|---------|----------|-------------|
| GET | `/admin/export-finetuning` | Exporte les données pour fine-tuning |

**Réponse :**
- Téléchargement du fichier JSONL (SFT ou DPO)
- Headers personnalisés : `X-Total-SFT`, `X-Total-DPO`

---

## ⚙️ Configuration

### Variables d'Environnement

Créer un fichier `.env` à la racine du projet :

```env
# Configuration Ollama (modèle principal)
OLLAMA_URL="http://localhost:11434/api/generate"
OLLAMA_URL_EMBEDDING="http://localhost:11434/api/embed"
MODEL_IA="ministral-3:14b"
MODEL_IA_EMBEDDING="qwen3-embedding:4b"

# Configuration LMStudio (alternative)
LMSTUDIO_URL="http://192.168.69.42:1234/api/v1/chat"
MODEL_IA_LMSTUDIO="google/gemma-4-e4b"

# CORS
CORS_ORIGINS=["http://comant-dev", "http://comant"]

# Base de données MySQL
DB_HOST=localhost
DB_PORT=3306
DB_NAME=comant
DB_USER=root
DB_PASSWORD=
```

### Modèles Supportés

| Fournisseur | Modèle | Usage |
|-------------|--------|-------|
| Ollama | `ministral-3:14b` | Génération de texte (principal) |
| Ollama | `qwen3-embedding:4b` | Embeddings (4096 dimensions) |
| LMStudio | `google/gemma-4-e4b` | Alternative à Ollama |

---

## 🚀 Installation et Exécution

### Prérequis

- Python 3.10+
- MySQL 5.7+
- Ollama (pour l'exécution locale des modèles)

### Étapes d'Installation

#### 1. Créer un environnement virtuel

```bash
python -m venv venv
```

#### 2. Activer l'environnement

**Windows (CMD) :**
```cmd
venv\Scripts\activate
```

**Windows (PowerShell) :**
```powershell
.\venv\Scripts\Activate.ps1
```

#### 3. Installer les dépendances

```bash
pip install -r requirements.txt
```

#### 4. Configurer les variables d'environnement

Copier le fichier `.env.example` (si disponible) ou créer `.env` manuellement avec les valeurs appropriées.

#### 5. Installer Ollama (pour les modèles IA locaux)

**Windows (PowerShell) :**
```powershell
irm https://ollama.com/install.ps1 | iex
```

#### 6. Télécharger les modèles requis

```bash
ollama pull ministral-3:14b
ollama pull qwen3-embedding:4b
```

> ⚠️ **Note :** Le téléchargement peut prendre du temps selon votre connexion.

#### 7. Démarrer Ollama

```bash
ollama serve
```

> Ollama doit être en cours d'exécution avant de lancer l'API.

#### 8. Lancer l'application

```bash
uvicorn app.main:app --reload
```

**Options :**
- `--reload` : Recharge automatiquement lors des changements de code
- `--host 0.0.0.0` : Accès depuis le réseau local
- `--port 8000` : Port personnalisé

#### 9. Accéder à l'API

Ouvrir dans un navigateur ou utiliser un client API :
```
http://localhost:8000
```

**Documentation interactive (Swagger UI) :**
```
http://localhost:8000/docs
```

**Documentation alternative (ReDoc) :**
```
http://localhost:8000/redoc
```

---

## 🧪 Tests

### Exécuter les tests

#### Tests d'intentions

```bash
# Depuis la racine du projet
python -m app.tests.tests intentions
```

#### Tests de requêtes SQL

```bash
python -m app.tests.tests sql
```

#### Tests avec un fournisseur spécifique

```bash
# Avec Ollama
python -m app.tests.tests ollama intentions

# Avec LMStudio
python -m app.tests.tests lmstudio sql
```

#### Tester le comptage de tokens

Accéder à l'endpoint :
```
GET http://localhost:8000/tests/tokens
```

### Fichiers de test

- `app/tests/intentions_test.json` - Cas de test pour la classification d'intentions
- `app/tests/requetes_test.json` - Cas de test pour la génération SQL

---

## 📁 Structure du Projet

```
chatbot-api/
├── .env                           # Configuration
├── .gitignore
├── README.md                      # Documentation (ce fichier)
├── requirements.txt               # Dépendances Python
├── prompt_recherche.txt          # Documentation des prompts
│
├── app/
│   ├── __init__.py
│   ├── main.py                    # Application FastAPI
│   ├── config.py                  # Configuration Pydantic
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   └── chat.py                # Schémas Pydantic
│   │
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── chat.py                # Endpoint /chat
│   │   ├── name.py                # Endpoint /name
│   │   └── admin.py               # Endpoint /admin
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── router.py              # Routage principal
│   │   ├── ollama.py              # Client Ollama
│   │   ├── database.py            # Client MySQL
│   │   ├── embedding.py           # Recherche sémantique
│   │   ├── embedding_generation.py # Génération d'embeddings
│   │   ├── intention.py           # Classification
│   │   ├── entity_cache.py        # Cache des entités
│   │   ├── conversation_name.py   # Génération de noms
│   │   └── finetuning_couples.py # Export fine-tuning
│   │
│   ├── prompts/
│   │   ├── __init__.py
│   │   ├── intention.py           # Prompt classification
│   │   ├── recherche.py           # Prompt SQL
│   │   ├── affinage.py            # Prompt affinage
│   │   ├── hybrid_research.py     # Prompts hybride
│   │   ├── entity_extraction.py   # Prompt extraction
│   │   ├── recherche_semantique_text.py
│   │   ├── conversation_name.py
│   │   ├── aide.py
│   │   ├── salutation.py
│   │   └── hors_perimetre.py
│   │
│   └── tests/
│       ├── __init__.py
│       ├── tests.py               # Fonctions de test
│       ├── intentions_test.json   # Cas de test intentions
│       └── requetes_test.json     # Cas de test SQL
│
├── exports/
│   ├── sft/                       # Export SFT
│   └── dpo/                       # Export DPO
│
└── Modelfiles/                    # Configurations de modèles
```

---

## 📊 Exemples d'Utilisation

### Exemple 1 : Recherche Simple

**Requête :**
```json
POST /chat/stream
{
  "message": "Mes tickets ouverts",
  "user_id": 5,
  "historique": [],
  "last_message_id": 0,
  "intention": "",
  "research_id": 0
}
```

**Réponse (streaming) :**
```
{"intention": "recherche"}

[STREAM_START]

<p>Résultats de la recherche : 15 tickets trouvés.</p>
SELECT DISTINCT t.id, t.code, t.summary FROM ticket t WHERE t.creator_id = 5 AND t.status = 'Ouvert' AND t.type != 'Group'
... (résultats)
```

### Exemple 2 : Recherche Sémantique

**Requête :**
```json
POST /chat/stream
{
  "message": "Tickets qui parlent de cinématique",
  "user_id": 5,
  "historique": [],
  "last_message_id": 0,
  "intention": "",
  "research_id": 0
}
```

**Processus :**
1. Classification -> `recherche_semantique`
2. Nettoyage du texte
3. Génération d'embedding
4. Recherche de similarité
5. Retour des tickets pertinents

### Exemple 3 : Recherche Hybride

**Requête :**
```json
POST /chat/stream
{
  "message": "Tickets du projet CAO qui parlent de bugs de login",
  "user_id": 5,
  "historique": [],
  "last_message_id": 0,
  "intention": "",
  "research_id": 0
}
```

**Processus :**
1. Classification -> `recherche_hybride`
2. Décomposition en filtres + thème
3. Génération de deux requêtes SQL
4. Combinaison intelligente
5. Exécution et retour

### Exemple 4 : Affinage

**Contexte :** L'utilisateur a déjà effectuer une recherche (ID: 123)

**Requête :**
```json
POST /chat/stream
{
  "message": "Seulement les fermés",
  "user_id": 5,
  "historique": [...],
  "last_message_id": 456,
  "intention": "affinage",
  "research_id": 123
}
```

**Processus :**
1. Classification -> `affinage`
2. Récupération de la requête SQL précédente
3. Modification avec le nouveau filtre
4. Exécution et retour

### Exemple 5 : Génération de Nom de Conversation

**Requête :**
```json
POST /name/create
{
  "historique": [
    {"role": "user", "content": "Bonjour"},
    {"role": "bot", "content": "Bonjour !"},
    {"role": "user", "content": "Mes tickets ouverts du projet CAO"}
  ],
  "conversation_id": 789
}
```

**Réponse :**
```json
{
  "name": "Recherche des tickets ouverts du projet CAO"
}
```

---

## 🔄 Fine-Tuning et Export

### Export des Données de Fine-Tuning

L'API permet d'exporter les données de conversation pour entrainer (fine-tuner) les modèles IA.

#### Deux formats supportés :

1. **SFT (Supervised Fine-Tuning)**
   - Couples (message utilisateur -> SQL correct)
   - Format : ShareGPT JSONL
   - Basé sur les feedbacks positifs (`like`)

2. **DPO (Direct Preference Optimization)**
   - Triplets (message -> SQL incorrect -> SQL correct)
   - Format : JSONL avec champs `chosen`/`rejected`
   - Basé sur les feedbacks négatifs (`dislike`)

#### Comment exporter :

**Via API :**
```bash
curl http://localhost:8000/admin/export-finetuning -o finetuning.jsonl
```

**Via le code :**
```python
from app.services.finetuning_couples import export_finetuning_service
export_finetuning_service()
```

**Fichiers générés :**
- `exports/sft/finetuning_sft_{timestamp}.jsonl`
- `exports/dpo/finetuning_dpo_{timestamp}.jsonl`

### Structure des Fichiers Exportés

**SFT :**
```json
{"messages": [{"role": "system", "content": "Tu es un assistant SQL..."}, {"role": "user", "content": "Mes tickets ouverts"}, {"role": "assistant", "content": "SELECT DISTINCT t.id, t.code, t.summary FROM ticket t WHERE t.creator_id = 5 AND t.status = 'Ouvert' AND t.type != 'Group'"}]}
```

**DPO :**
```json
{"prompt": [{"role": "system", "content": "Tu es un assistant SQL..."}, {"role": "user", "content": "Mes tickets ouverts"}], "chosen": {"role": "assistant", "content": "SELECT ... correct"}, "rejected": {"role": "assistant", "content": "SELECT ... incorrect"}}
```

---

## 🛠️ Développement

### Ajouter une Nouvelle Intention

1. **Modifier le prompt** dans `app/prompts/intention.py`
2. **Ajouter le cas** dans `INTENTIONS` dans `app/services/intention.py`
3. **Ajouter le handler** dans `SIMPLE_INTENT_PROMPTS` dans `app/services/router.py`
4. **Créer le prompt système** dans `app/prompts/`

### Ajouter un Nouveau Type d'Entité

1. **Ajouter à `CACHEABLE_COLUMNS`** dans `app/services/entity_cache.py`
2. **Mettre à jour le prompt d'extraction** si nécessaire
3. **Tester la validation**

### Étendre les Capacités de Recherche

1. **Modifier le prompt SQL** dans `app/prompts/recherche.py`
2. **Ajouter des valeurs de référence** si besoin
3. **Tester avec de nouveaux cas**

---

## 📝 Notes Techniques

### Sécurité

- Seules les requêtes SELECT sont autorisées
- Validation des colonnes et tables contre le schéma
- Echappement des caractères spéciaux
- Restriction CORS configurable

### Performances

- Cache des entités (30 minutes par défaut)
- Streaming des réponses pour une meilleure UX
- Embeddings pré-calculés pour les tickets

### Limitations

- Ollama doit être en cours d'exécution localement
- La base de données doit être accessible
- Les modèles doivent être téléchargés avant utilisation

---