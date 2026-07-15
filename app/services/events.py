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
from typing import Callable, Optional

STREAM_START = "[STREAM_START]\n"

@dataclass
class EventSink:
    """Accumulateur d'événements structurés produits pendant un tour de chat.
    
    Les événements précoces (early events) sont émis immédiatement via un callback
    pour permettre au front d'afficher "recherche en cours" avant que la recherche ne commence.
    """

    _events: list[dict] = field(default_factory=list)
    _on_early_emit: Optional[Callable[[dict], None]] = None
    _early_emitted_intentions: set = field(default_factory=set)

    def set_early_callback(self, callback: Optional[Callable[[dict], None]]) -> None:
        """Configure un callback pour les événements précoces (early events)."""
        self._on_early_emit = callback

    def emit(self, event: str, **data) -> None:
        self._events.append({"event": event, **data})

    def emit_early(self, event: str, **data) -> None:
        """Émet un événement et l'envoie immédiatement via le callback si configuré."""
        evt = {"event": event, **data}
        self._events.append(evt)
        if self._on_early_emit:
            self._on_early_emit(evt)

    def intention(self, intention: str) -> None:
        self.emit("intention", intention=intention)

    def early_intention(self, intention: str) -> None:
        """Émet une intention comme événement précoce (envoyé immédiatement au front)."""
        # Marquer cette intention comme déjà envoyée early
        self._early_emitted_intentions.add(intention)
        self.emit_early("intention", intention=intention)

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
        self._early_emitted_intentions.clear()
        return events

    def serialize(self) -> str:
        """Sérialise et vide : une ligne JSON par événement (terminées par \\n)."""
        return "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in self.drain())
