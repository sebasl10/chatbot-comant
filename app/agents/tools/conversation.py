"""
Tool de recherche dans les conversations passées (backed Chroma).

Les résumés ne sont JAMAIS injectés d'office dans les prompts : ce sont des faits sur
ce qui s'est passé, pas des règles à appliquer. On les récupère seulement quand
l'utilisateur pose explicitement une question sur un échange antérieur — sans quoi ils
concurrenceraient les souvenirs (`app/agents/tools/memory.py`), qui eux sont faits pour
être réinjectés automatiquement.
"""

from pydantic_ai import RunContext

from app.agents.deps import ChatDeps
from app.services import vectorstore as vs


async def search_past_conversations(ctx: RunContext[ChatDeps], query: str) -> dict:
    """
    Retrouve ce qui a été dit dans les conversations PRÉCÉDENTES de l'utilisateur.

    À utiliser uniquement quand l'utilisateur fait référence à un échange antérieur qui
    n'est PAS dans l'historique fourni : « de quoi avions-nous parlé la semaine dernière ? »,
    « qu'avions-nous conclu sur les annotations 3D ? », « j'avais déjà cherché ça, non ? ».
    N'appelle pas cet outil pour une question portant sur la conversation en cours :
    l'historique suffit.

    Args:
        query: le sujet recherché, extrait de la question (ex: "annotations 3D",
               "statistiques de temps par salarié")

    Returns:
        dict avec les clés:
        - count: nombre de conversations retrouvées
        - conversations: liste de {name, date, summary}, de la plus proche à la moins proche

        Chaque `summary` résume une conversation ENTIÈRE : il peut couvrir plusieurs
        recherches et plusieurs sujets. N'en reprends que ce qui répond à la question posée,
        reformulé — ne restitue jamais un résumé en entier.
    """
    print("[TOOL CALL] search_past_conversations")
    print(f"Query: {query}")

    results = await vs.search_conversation_summaries(
        user_id=ctx.deps.user_id,
        query=query,
        exclude_conversation_id=ctx.deps.conversation_id,
    )

    conversations = [
        {
            "name": r["metadata"].get("name") or "Conversation sans nom",
            "date": (r["metadata"].get("updated_at") or "")[:10],
            "summary": r["summary"],
        }
        for r in results
    ]
    return {"count": len(conversations), "conversations": conversations}
