"""Protocole d'événements streamés vers le front.

Le front attend, sur ``/chat/stream`` : d'abord des lignes JSON de métadonnées,
puis la sentinelle ``[STREAM_START]``, puis le texte de la réponse en langage
naturel. On généralise ce contrat : chaque événement est une ligne JSON portant
une clé ``event`` qui décrit sa nature.

Types d'événements :
- ``intention``  : {"event": "intention", "intention": ...}            (compat)
- ``research``   : {"event": "research", "research_id": ..., "sql": ...} → redirection onglet Recherche + affichage
- ``action``     : {"event": "action", "name": "rename_research"|"delete_research", ...} → remplace les boutons
- ``correction`` : {"event": "correction", "type": ..., "memory": ...}   (compat)
- ``error``      : {"event": "error", "message": ...}

Les agents/tools n'émettent pas directement sur le réseau : ils *accumulent* des
événements dans ``ChatDeps.events`` (voir ``app/agents/deps.py``). L'orchestrateur
les sérialise avant ``[STREAM_START]``.
"""
import json
from dataclasses import dataclass, field

STREAM_START = "[STREAM_START]\n"

@dataclass
class EventSink:
    """Accumulateur d'événements structurés produits pendant un tour de chat."""

    _events: list[dict] = field(default_factory=list)

    def emit(self, event: str, **data) -> None:
        self._events.append({"event": event, **data})

    def intention(self, intention: str) -> None:
        self.emit("intention", intention=intention)

    def research(self, research_id, sql: str) -> None:
        self.emit("research", research_id=research_id, sql=sql)

    def action(self, name: str, **data) -> None:
        self.emit("action", intention=name, **data)

    def correction(self, type: str, memory: str) -> None:
        self.emit("correction", type=type, memory=memory)

    def error(self, message: str) -> None:
        self.emit("error", message=message)

    def drain(self) -> list[dict]:
        """Retourne les événements accumulés et vide le tampon."""
        events, self._events = self._events, []
        return events

    def serialize(self) -> str:
        """Sérialise et vide : une ligne JSON par événement (terminées par \\n)."""
        return "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in self.drain())
