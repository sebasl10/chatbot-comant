"""
Dépendances injectées dans tous les agents et tools (Pydantic AI ``deps_type``).

Un unique ``ChatDeps`` circule du superviseur vers les spécialistes puis vers les
tools via ``RunContext.deps``. Il porte le contexte utilisateur.
"""
import json

from dataclasses import dataclass, field
from app.services.events import EventSink

@dataclass
class ChatDeps:
    user_id: int
    username: str | None = None
    
    # Infos passées par le front pour l'affinage
    research_id: int = 0
    last_message_id: int = 0

    historique: list[dict] = field(default_factory=list)
    events: EventSink = field(default_factory=EventSink)
    message: str = ""
    memory_query_embedding: list[float] | None = None

    # Dernière requête SQL exécutée avec succès par le tool run_sql
    last_sql: str | None = None
    last_count: int = 0

    # Mode courant de l'agent SQL : "recherche" (nouvelle recherche) ou "affinage" (modification d'une recherche existante).
    mode: str = "recherche"
    
    # Requête SQL précédente à affiner (renseignée en mode affinage).
    previous_sql: str | None = None
    
    # Dépendances pour la persistance de statistiques.
    last_stats_sql: str | None = None
    external_sql: str | None = None

    # Résultat brut de la dernière requête stats 
    last_result: list[dict] | None = None
    last_stats_columns: list[str] = field(default_factory=list)

    # Présentation de la statistique choisie par l'agent
    graph_type: str | None = None
    description: str | None = None
    labels: list[dict] | None = None
