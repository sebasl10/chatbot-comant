"""
Génération des résumés de conversation (collection Chroma ``conversation_summaries``).

Le résumé est produit HORS du flux de chat : il coûte un appel au modèle et n'a aucun
intérêt tant que la conversation est en cours. Ce script traite les conversations « au
repos » (aucun message depuis ``--idle-minutes``) et saute celles dont le résumé est
déjà à jour, ce qui le rend rejouable à volonté — typiquement via une tâche planifiée.

Usage :
    python -m app.scripts.generate_conversation_summaries              # les conversations au repos
    python -m app.scripts.generate_conversation_summaries --idle-minutes 60
    python -m app.scripts.generate_conversation_summaries --conversation 42 --force
    python -m app.scripts.generate_conversation_summaries list         # ce qui est stocké
"""

import argparse
import asyncio

from app.agents.specialists.conversation_summary import summarize_conversation
from app.config import settings
from app.services import vectorstore as vs
from app.services.database import (
    get_conversation,
    get_conversation_messages,
    get_conversations_to_summarize,
)

# En dessous, il n'y a rien à résumer (une question sans réponse, un « bonjour » isolé).
MIN_MESSAGES = 3


async def _summarize_one(conversation: dict, force: bool) -> str:
    """
    Résume une conversation si nécessaire. Renvoie l'état : "resume", "a jour" ou "ignoree".
    """
    conversation_id = conversation["conversation_id"]
    last_message_id = conversation["last_message_id"]
    name = conversation.get("name") or ""

    if not force:
        deja_resume = await vs.get_summarized_message_id(conversation_id)
        if deja_resume >= last_message_id:
            return "a jour"

    messages = await asyncio.to_thread(get_conversation_messages, conversation_id)
    if len(messages) < MIN_MESSAGES:
        return "ignoree"

    summary = await summarize_conversation(messages)
    await vs.upsert_conversation_summary(
        conversation_id=conversation_id,
        user_id=conversation["user_id"],
        document=summary.to_document(name),
        last_message_id=last_message_id,
        conversation_name=name,
        sujets=summary.sujets,
        issue=summary.issue,
    )
    print(f"     objectif : {summary.objectif}")
    return "resume"


async def generate(idle_minutes: int, limit: int, force: bool, conversation_id: int) -> None:
    if conversation_id:
        conversation = await asyncio.to_thread(get_conversation, conversation_id)
        if not conversation:
            print(f"  ❌ Conversation {conversation_id} introuvable.")
            return
        messages = await asyncio.to_thread(get_conversation_messages, conversation_id)
        if not messages:
            print(f"  ❌ Aucun message pour la conversation {conversation_id}.")
            return
        conversations = [{**conversation, "last_message_id": messages[-1]["id"]}]
    else:
        conversations = await asyncio.to_thread(get_conversations_to_summarize, idle_minutes, limit)

    print("=" * 70)
    print("  Génération des résumés de conversation")
    print("=" * 70)
    print(f"  Chroma : {settings.chroma_http_url}")
    print(f"  {len(conversations)} conversation(s) à examiner\n")

    compteurs = {"resume": 0, "a jour": 0, "ignoree": 0, "erreur": 0}
    for conversation in conversations:
        cid = conversation["conversation_id"]
        libelle = conversation.get("name") or "sans nom"
        try:
            etat = await _summarize_one(conversation, force)
        except Exception as e:
            etat = "erreur"
            print(f"  ❌ Conversation {cid} ({libelle}) : {e}")
        else:
            symbole = {"resume": "✅", "a jour": "⏭️ ", "ignoree": "➖"}[etat]
            print(f"  {symbole} Conversation {cid} ({libelle}) : {etat}")
        compteurs[etat] += 1

    print(
        f"\n  {compteurs['resume']} résumé(s) écrit(s), {compteurs['a jour']} déjà à jour, "
        f"{compteurs['ignoree']} trop courte(s), {compteurs['erreur']} en erreur."
    )


async def list_summaries() -> None:
    """Liste les résumés stockés."""
    col = await vs.summaries_collection()
    res = await col.get(include=["documents", "metadatas"])
    ids = res.get("ids", [])

    print("=" * 70)
    print(f"  Résumés de conversation ({len(ids)} au total)")
    print("=" * 70)
    if not ids:
        print("  Aucun résumé stocké.")
        return

    for i, (doc, meta) in enumerate(zip(res["documents"], res["metadatas"], strict=False), 1):
        meta = meta or {}
        print(
            f"\n  {i}. conversation {meta.get('conversation_id')} "
            f"« {meta.get('name') or 'sans nom'} » "
            f"— utilisateur {meta.get('user_id')} — maj {meta.get('updated_at', '?')[:19]}"
        )
        for ligne in (doc or "").split("\n"):
            print(f"     {ligne}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Résumés de conversation (collection Chroma)")
    parser.add_argument("command", nargs="?", choices=["list"], help="list")
    parser.add_argument(
        "--idle-minutes",
        type=int,
        default=30,
        help="Ancienneté minimale du dernier message pour qu'une conversation soit résumée",
    )
    parser.add_argument("--limit", type=int, default=50, help="Nombre max de conversations")
    parser.add_argument(
        "--force", action="store_true", help="Régénère même si le résumé est à jour"
    )
    parser.add_argument(
        "--conversation", type=int, default=0, help="Ne traiter qu'une conversation précise"
    )
    args = parser.parse_args()

    if args.command == "list":
        await list_summaries()
    else:
        await generate(args.idle_minutes, args.limit, args.force, args.conversation)


if __name__ == "__main__":
    asyncio.run(main())
