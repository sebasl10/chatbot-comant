"""Accès aux dépendances (``ChatDeps``) depuis un tool LangChain.

Équivalent LangGraph de ``RunContext.deps`` de Pydantic AI : on transporte le
``ChatDeps`` dans ``RunnableConfig["configurable"]["deps"]``, injecté à l'invocation
du superviseur et propagé dans tout le graphe jusqu'aux tools.

Un tool déclare un paramètre ``config: RunnableConfig`` (auto-injecté par LangChain,
invisible pour le LLM) et appelle ``deps_from_config(config)``.
"""
from langchain_core.runnables import RunnableConfig

from app.agents.deps import ChatDeps


def deps_from_config(config: RunnableConfig) -> ChatDeps:
    deps = (config or {}).get("configurable", {}).get("deps")
    if deps is None:
        raise RuntimeError("ChatDeps absent de la config (configurable.deps).")
    return deps
