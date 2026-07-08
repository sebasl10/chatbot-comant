"""
Dépendances injectées dans tous les agents et tools (Pydantic AI ``deps_type``).

Un unique ``ChatDeps`` circule du superviseur vers les spécialistes puis vers les
tools via ``RunContext.deps``. Il porte le contexte utilisateur, l'historique de
conversation, l'identifiant de la recherche courante (pour l'affinage) et le
collecteur d'événements à streamer vers le front.
"""
from dataclasses import dataclass, field
from app.services.events import EventSink

@dataclass
class ChatDeps:
    user_id: int
    message: str
    username: str | None = None
    
    # Infos passées par le front pour l'affinage
    research_id: int = 0
    last_message_id: int = 0
    
    historique: list[dict] = field(default_factory=list)
    events: EventSink = field(default_factory=EventSink)

    # Dernière requête SQL exécutée avec succès par le tool run_sql, et son
    # nombre de résultats. La couche de délégation les utilise pour persister
    # la recherche (create_research / update_sql) de façon déterministe
    last_sql: str | None = None
    last_count: int = 0

    # Mode courant de l'agent SQL : "recherche" (nouvelle recherche) ou
    # "affinage" (modification d'une recherche existante). Positionné par la
    # couche de délégation du superviseur avant d'invoquer l'agent SQL.
    mode: str = "recherche"
    # Requête SQL précédente à affiner (renseignée en mode affinage).
    previous_sql: str | None = None
