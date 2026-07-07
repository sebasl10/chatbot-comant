"""Validation LIVE de bout en bout du superviseur (Ollama + MySQL + .env requis).

Exécute l'orchestrateur exactement comme l'endpoint /chat/stream, mais en CLI,
et affiche le flux (événements + texte). Pratique pour tester chaque capacité.

Exemples :
    python -m app.scripts.check_agent_live 1 "bonjour"
    python -m app.scripts.check_agent_live 1 "cherche les tickets du projet Comant2026"
    python -m app.scripts.check_agent_live 1 "les tickets qui parlent de cinématique"
    python -m app.scripts.check_agent_live 1 "garde seulement ceux qui sont ouverts"
    python -m app.scripts.check_agent_live 1 "sauvegarde cette recherche sous Bugs"
    python -m app.scripts.check_agent_live 1 "quand je dis cinématique, inclus vitesse de rotation"
"""
import asyncio
import sys

from app.agents.deps import ChatDeps
from app.agents.orchestrator import run_chat_stream
from app.services.database import get_username


async def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: python -m app.scripts.check_agent_live <user_id> <message> [research_id]")
        raise SystemExit(1)

    user_id = int(sys.argv[1])
    message = sys.argv[2]
    research_id = int(sys.argv[3]) if len(sys.argv) > 3 else 0

    deps = ChatDeps(
        user_id=user_id,
        research_id=research_id,
        username=await asyncio.to_thread(get_username, user_id),
    )

    print(f"\n>>> {message}\n" + "─" * 60)
    async for chunk in run_chat_stream(message, deps):
        print(chunk, end="", flush=True)
    print("\n" + "─" * 60)


if __name__ == "__main__":
    asyncio.run(main())
