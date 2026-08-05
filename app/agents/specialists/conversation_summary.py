"""
ConversationSummaryAgent — résume une conversation terminée.

Appelé hors du flux de chat, par le script de génération des résumés : produire un
résumé coûte un appel au modèle et n'a aucun intérêt tant que la conversation est
encore en cours.

Le résumé est un artefact DÉRIVÉ des messages stockés en base. Il ne contient donc pas
ce que MySQL sait déjà restituer (le SQL généré, les intentions, les messages bruts),
mais ce qu'aucune requête ne peut reconstituer : l'intention réelle, ce qui a marché,
ce qui a été corrigé.
"""

from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from app.agents.model import FACTUAL_SETTINGS, get_agent_model
from app.agents.prompts.agent_conversation_summary import AGENT_CONVERSATION_SUMMARY_PROMPT

MAX_MESSAGE_CHARS = 1500


class ConversationSummary(BaseModel):
    """Résumé structuré d'une conversation."""

    objectif: str = Field(description="Ce que l'utilisateur cherchait, en une ou deux phrases")
    sujets: list[str] = Field(
        default_factory=list, description="Projets, clients, produits et thèmes abordés"
    )
    resultats: list[str] = Field(
        default_factory=list, description="Ce que les recherches ou statistiques ont donné"
    )
    corrections: list[str] = Field(
        default_factory=list, description="Ce que l'utilisateur a corrigé ou reproché"
    )
    issue: Literal["aboutie", "abandonnee", "en_suspens"] = "en_suspens"

    def to_document(self, conversation_name: str | None = None) -> str:
        """
        Rend le résumé sous forme de récit — c'est CE texte qui est embeddé, parce que
        c'est à lui que ressembleront les questions (« de quoi avait-on parlé ? »).
        Les identifiants et dates, eux, vivent dans les métadonnées Chroma.
        """
        lignes = []
        if conversation_name:
            lignes.append(f"Conversation : {conversation_name}")
        lignes.append(f"Objectif : {self.objectif}")
        if self.sujets:
            lignes.append(f"Sujets abordés : {', '.join(self.sujets)}")
        if self.resultats:
            lignes.append("Résultats : " + " ; ".join(self.resultats))
        if self.corrections:
            lignes.append("Corrections de l'utilisateur : " + " ; ".join(self.corrections))
        lignes.append(f"Issue : {self.issue}")
        return "\n".join(lignes)


conversation_summary_agent = Agent(
    get_agent_model(),
    output_type=ConversationSummary,
    system_prompt=AGENT_CONVERSATION_SUMMARY_PROMPT,
    retries=2,
    model_settings=FACTUAL_SETTINGS,
)


def _format_messages(messages: list[dict]) -> str:
    """Met les messages à plat pour le prompt, en tronquant les plus longs."""
    lignes = []
    for msg in messages:
        role = "Utilisateur" if msg.get("sender_role") in ("user", "utilisateur") else "Assistant"
        content = (msg.get("content") or "").strip()
        if not content:
            continue
        if len(content) > MAX_MESSAGE_CHARS:
            content = content[:MAX_MESSAGE_CHARS] + " […]"

        annotations = []
        if msg.get("intention"):
            annotations.append(f"intention={msg['intention']}")
        if msg.get("feedback"):
            annotations.append(f"retour utilisateur={msg['feedback']}")
        suffixe = f"  ({', '.join(annotations)})" if annotations else ""

        lignes.append(f"{role} : {content}{suffixe}")
    return "\n".join(lignes)


async def summarize_conversation(messages: list[dict]) -> ConversationSummary:
    """Produit le résumé structuré d'une conversation à partir de ses messages."""
    prompt = "Voici la conversation à résumer :\n\n" + _format_messages(messages)
    result = await conversation_summary_agent.run(prompt)
    return result.output
