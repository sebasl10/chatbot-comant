"""
Garde-fou contre les sorties inexploitables des modèles locaux.

Deux dérapages sont filtrés, tous deux observés avec Ministral servi via Ollama :

1. **L'appel d'outil qui fuite en texte** — le modèle émet son appel natif dans le
   texte de réponse au lieu de passer par le tool-calling de l'API
   OpenAI-compatible, par ex. :

   semantic_ticket_search[ARGS]{"query": "..."}

2. **Le dump de code source** — au moment de rédiger sa phrase finale, le modèle
   bascule en mode « complétion de code » et écrit une implémentation Python des
   tools qu'il vient d'appeler, préfixée du séparateur de fichiers du corpus de
   code de Mistral :

   +++++ assistant_tools.py
   from typing import List, Dict
   def run_stats_sql(sql: str) -> Dict:
   ...

Dans les deux cas ce texte ne doit jamais être affiché à l'utilisateur : on force
le modèle à corriger le tir via ``ModelRetry``.
"""

import re

from pydantic_ai import Agent, ModelRetry

_LEAK_PATTERNS = [
    re.compile(
        r"[a-zA-Z_][a-zA-Z0-9_]*\s*\[ARGS\]\s*\{"
    ),  # nom_outil[ARGS]{...} (format natif Mistral)
    re.compile(r"\[TOOL_CALLS\]"),  # préfixe natif Mistral
    re.compile(r"<tool_call>", re.IGNORECASE),  # format Hermes/Qwen
    re.compile(
        r'"name"\s*:\s*"[a-zA-Z_][a-zA-Z0-9_]*"\s*,\s*"arguments"\s*:'
    ),  # JSON générique {"name": .., "arguments": ..}
    re.compile(
        r"^\s*[a-z_][a-z0-9_]*\(\s*[\"{]"
    ),  # nom_outil("...") / nom_outil({...}) en début de réponse
]

# Aucun agent ne répond légitimement par du code : ils rédigent tous UNE phrase en
# français. Ces motifs sont donc cherchés sur TOUTE la réponse, ligne par ligne.
_CODE_DUMP_PATTERNS = [
    re.compile(r"^\s*\+{3,}\s*\S+\.\w+\s*$", re.MULTILINE),  # séparateur `+++++ main.py`
    re.compile(r"^\s*(from\s+[\w.]+\s+)?import\s+[\w.*]+", re.MULTILINE),  # import python
    re.compile(r"^\s*(async\s+)?def\s+\w+\s*\(", re.MULTILINE),  # définition de fonction
    re.compile(r"^\s*class\s+\w+\s*[(:]", re.MULTILINE),  # définition de classe
    re.compile(r"^\s*@\w+(\.\w+)*\s*\(", re.MULTILINE),  # décorateur (@app.post(...))
    re.compile(r"```"),  # bloc de code markdown
]

_TOOL_CALL_RETRY_MESSAGE = (
    "Tu as écrit un appel d'outil sous forme de texte au lieu de l'exécuter. "
    "N'écris jamais le nom d'un outil ni ses arguments en texte libre : "
    "appelle réellement l'outil via le mécanisme de function calling, ou "
    "réponds normalement en langage naturel si aucun outil n'est nécessaire."
)

_CODE_DUMP_RETRY_MESSAGE = (
    "Tu as répondu avec du code source au lieu de t'adresser à l'utilisateur. "
    "Les outils que tu viens d'appeler sont déjà implémentés côté back-end : tu n'as "
    "rien à écrire à leur sujet. Reprends ta réponse sous la forme d'une phrase en "
    "français adressée à l'utilisateur, sans aucun code, import, définition de "
    "fonction ou de classe, ni bloc ```."
)


def looks_like_leaked_tool_call(text: str) -> bool:
    """Détecte si ``text`` ressemble à un appel d'outil qui a fuité au lieu d'être exécuté."""
    if not text:
        return False
    return any(pattern.search(text) for pattern in _LEAK_PATTERNS)


def looks_like_code_dump(text: str) -> bool:
    """Détecte si ``text`` est du code source au lieu d'une réponse à l'utilisateur."""
    if not text:
        return False
    return any(pattern.search(text) for pattern in _CODE_DUMP_PATTERNS)


def unusable_output_reason(text: str) -> str | None:
    """
    Renvoie le message de correction à donner au modèle si ``text`` est inexploitable,
    ``None`` si la réponse est affichable telle quelle.
    """
    if looks_like_leaked_tool_call(text):
        return _TOOL_CALL_RETRY_MESSAGE
    if looks_like_code_dump(text):
        return _CODE_DUMP_RETRY_MESSAGE
    return None


def is_unusable_output(text: str) -> bool:
    """La réponse est-elle inaffichable (fuite d'appel d'outil ou dump de code) ?"""
    return unusable_output_reason(text) is not None


def guard_agent_output(agent: Agent) -> None:
    """
    Enregistre sur ``agent`` un output_validator qui force un ``ModelRetry`` quand la
    sortie n'est pas une réponse en langage naturel : appel d'outil écrit en texte au
    lieu d'être exécuté, ou dump de code source.
    """

    @agent.output_validator
    def _reject_unusable_output(data: str) -> str:
        if isinstance(data, str):
            reason = unusable_output_reason(data)
            if reason:
                raise ModelRetry(reason)
        return data
