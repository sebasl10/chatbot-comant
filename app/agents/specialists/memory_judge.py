"""
MemoryJudgeAgent — réconciliation mémoire à l'écriture (couche 1).

Appelé par ``save_memory`` (app/agents/tools/memory.py) avant d'écrire un
nouveau souvenir contextuel, sur les candidats renvoyés par
``vs.find_similar_contextual_memories`` (souvenirs existants dont la requête
déclencheuse est proche du nouveau trigger). Classe la relation entre le
nouveau souvenir et chaque candidat : le juge ne fait QUE classifier, il
n'écrit rien lui-même — c'est ``save_memory`` qui agit selon le verdict.

Un appel LLM séparé, invisible pour ``memory_agent`` : la similarité vectorielle
seule ne suffit pas à distinguer un doublon d'un conflit (deux règles
contradictoires sur la même situation sont aussi proches, en embedding, qu'une
paraphrase). Contrairement aux autres spécialistes, cet agent n'est pas
``deps_type=ChatDeps`` : il ne fait que classifier du texte, sans contexte
conversationnel.
"""

from typing import Literal
from pydantic import BaseModel
from pydantic_ai import Agent

from app.agents.model import get_agent_model
from app.agents.prompts.agent_memory_judge import AGENT_MEMORY_JUDGE_PROMPT

MemoryRelation = Literal["duplicate", "conflict", "complement", "unrelated"]


class MemoryVerdict(BaseModel):
    candidate_id: str
    relation: MemoryRelation
    # Requis uniquement si relation == "complement" : la règle fusionnée,
    # une phrase unique couvrant le candidat ET le nouveau souvenir.
    merged_content: str | None = None


memory_judge_agent = Agent(
    get_agent_model(),
    output_type=list[MemoryVerdict],
    system_prompt=AGENT_MEMORY_JUDGE_PROMPT,
    retries=2,
)


async def judge_candidates(new_trigger: str, new_content: str, candidates: list[dict]) -> list[MemoryVerdict]:
    """
    ``candidates`` : sortie de ``vs.find_similar_contextual_memories``
    (``{id, trigger, rule, distance}``). Renvoie un ``MemoryVerdict`` par
    candidat, dans le même ordre. Liste vide si ``candidates`` est vide.
    """
    if not candidates:
        return []

    candidates_text = "\n".join(
        f"- candidate_id={c['id']!r} (distance={c['distance']:.3f})\n"
        f"  trigger existant: {c['trigger']}\n"
        f"  règle existante: {c['rule']}"
        for c in candidates
    )
    prompt = (
        f"NOUVEAU souvenir :\n"
        f"  trigger: {new_trigger}\n"
        f"  règle: {new_content}\n\n"
        f"CANDIDATS ({len(candidates)}) :\n{candidates_text}"
    )
    result = await memory_judge_agent.run(prompt)
    return result.output
