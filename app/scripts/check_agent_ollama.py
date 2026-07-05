"""Vérification LIVE : le modèle Ollama fait-il bien du tool calling natif ?

À lancer quand Ollama tourne, avec un .env valide :

    python -m app.scripts.check_agent_ollama

Le script construit un agent Pydantic AI branché sur Ollama (`/v1`) avec un tool
factice `get_weather`. Si le modèle appelle le tool et intègre son résultat, le
tool calling natif fonctionne — prérequis de toute l'architecture agent.

En cas d'échec (le modèle ne supporte pas les function calls via `/v1`), basculer
`MODEL_IA_TOOLS` sur un modèle tool-capable (ex. `qwen2.5:14b`) dans le `.env`.
"""
import asyncio

from pydantic_ai import Agent, RunContext

from app.agents.deps import ChatDeps
from app.agents.model import get_agent_model


agent = Agent(
    get_agent_model(),
    deps_type=ChatDeps,
    system_prompt=(
        "Tu es un assistant de test. Quand on te demande la météo d'une ville, "
        "tu DOIS appeler l'outil get_weather. Réponds ensuite en une phrase."
    ),
)

_tool_called = {"value": False}


@agent.tool
def get_weather(ctx: RunContext[ChatDeps], ville: str) -> str:
    """Renvoie une météo factice pour une ville donnée."""
    _tool_called["value"] = True
    print(f"  [tool get_weather appelé] ville={ville}")
    return f"Il fait 21°C et ensoleillé à {ville}."


async def main() -> None:
    deps = ChatDeps(user_id=1, username="test")
    result = await agent.run("Quelle est la météo à Toulouse ?", deps=deps)
    print("\nRéponse du modèle :", result.output)
    print("Tool appelé :", _tool_called["value"])
    if _tool_called["value"]:
        print("\n✅ TOOL CALLING NATIF OK — l'architecture agent est viable avec ce modèle.")
    else:
        print(
            "\n⚠️  Le modèle n'a PAS appelé le tool. Vérifie que MODEL_IA_TOOLS "
            "pointe sur un modèle qui supporte le function calling (Mistral/Qwen)."
        )


if __name__ == "__main__":
    asyncio.run(main())
