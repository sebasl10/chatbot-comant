"""
Garde-fou contre les appels d'outils qui fuitent en texte brut.

Certains modèles locaux (ex. Ministral servi via Ollama) émettent parfois leur
appel d'outil natif directement dans le texte de réponse au lieu de passer par
le mécanisme structuré de tool-calling de l'API OpenAI-compatible, par ex. :

semantic_ticket_search[ARGS]{"query": "..."}

Ce texte ne doit jamais être affiché à l'utilisateur. On force le
modèle à corriger le tir via ``ModelRetry``.
"""

import re
from pydantic_ai import Agent, ModelRetry

_LEAK_PATTERNS = [
    re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*\s*\[ARGS\]\s*\{"),  # nom_outil[ARGS]{...} (format natif Mistral)
    re.compile(r"\[TOOL_CALLS\]"),  # préfixe natif Mistral
    re.compile(r"<tool_call>", re.IGNORECASE),  # format Hermes/Qwen
    re.compile(r'"name"\s*:\s*"[a-zA-Z_][a-zA-Z0-9_]*"\s*,\s*"arguments"\s*:'),  # JSON générique {"name": .., "arguments": ..}
    re.compile(r"^\s*[a-z_][a-z0-9_]*\(\s*[\"{]"),  # nom_outil("...") / nom_outil({...}) en début de réponse
]

_RETRY_MESSAGE = (
    "Tu as écrit un appel d'outil sous forme de texte au lieu de l'exécuter. "
    "N'écris jamais le nom d'un outil ni ses arguments en texte libre : "
    "appelle réellement l'outil via le mécanisme de function calling, ou "
    "réponds normalement en langage naturel si aucun outil n'est nécessaire."
)


def looks_like_leaked_tool_call(text: str) -> bool:
    """Détecte si ``text`` ressemble à un appel d'outil qui a fuité au lieu d'être exécuté."""
    if not text:
        return False
    return any(pattern.search(text) for pattern in _LEAK_PATTERNS)


def guard_against_tool_call_leak(agent: Agent) -> None:
    """
    Enregistre sur ``agent`` un output_validator qui force un ``ModelRetry``
    quand la sortie ressemble à un appel d'outil écrit en texte au lieu
    d'être réellement exécuté.
    """

    @agent.output_validator
    def _reject_leaked_tool_call(data: str) -> str:
        if isinstance(data, str) and looks_like_leaked_tool_call(data):
            raise ModelRetry(_RETRY_MESSAGE)
        return data
