# Mise en place

Créer et activer un environnement virtuel:
python -m venv venv
venv\Scripts\activate

Installer les dépendances:
pip install -r requirements.txt

Lancer l'application (depuis la racine chatbot-api):
uvicorn app.main:app --reload

# Modèle IA

Pour déployer le modèle IA en local, il faut installer ollama:
irm https://ollama.com/install.ps1 | iex

Ensuite, il faut télécharger le modèle souhaité
ollama run mistral-nemo