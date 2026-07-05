"""Vérification LIVE : le modèle Ollama fait-il bien du tool calling natif ?
(variante LangChain / ChatOllama)

À lancer quand Ollama tourne, avec un .env valide :

    python -m app.scripts.check_agent_ollama

Construit un agent LangGraph (`create_agent`) branché sur `ChatOllama` avec un tool
factice `get_weather`. Si le modèle appelle le tool et intègre son résultat, le tool
calling natif fonctionne — prérequis de toute l'architecture agent.

En cas d'échec, basculer `MODEL_IA_TOOLS` sur un modèle tool-capable (ex. `qwen2.5:14b`).
"""
import asyncio

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

from app.agents.model import get_agent_model

_tool_called = {"value": False}


@tool
def get_weather(ville: str) -> str:
    """Renvoie une météo factice pour une ville donnée."""
    _tool_called["value"] = True
    print(f"  [tool get_weather appelé] ville={ville}")
    return f"Il fait 21°C et ensoleillé à {ville}."


agent = create_agent(
    get_agent_model(),
    [get_weather],
    system_prompt=(
        "Tu es un assistant de test. Quand on te demande la météo d'une ville, "
        "tu DOIS appeler l'outil get_weather. Réponds ensuite en une phrase."
    ),
)


async def main() -> None:
    result = await agent.ainvoke(
        {"messages": [HumanMessage(content="Quelle est la météo à Toulouse ?")]}
    )
    print("\nRéponse du modèle :", result["messages"][-1].content)
    print("Tool appelé :", _tool_called["value"])
    if _tool_called["value"]:
        print("\n✅ TOOL CALLING NATIF OK — l'architecture agent LangChain est viable avec ce modèle.")
    else:
        print(
            "\n⚠️  Le modèle n'a PAS appelé le tool. Vérifie que MODEL_IA_TOOLS "
            "pointe sur un modèle qui supporte le function calling (Mistral/Qwen)."
        )


if __name__ == "__main__":
    asyncio.run(main())
