"""
MemoryJudgeAgent — réconciliation mémoire à l'écriture .

Appelé avant d'écrire un nouveau souvenir contextuel, sur les candidats renvoyés. Classe la relation entre le
nouveau souvenir et chaque candidat.
"""

from typing import Literal

from pydantic import BaseModel
from pydantic_ai import Agent

from app.agents.model import DETERMINISTIC_SETTINGS, get_agent_model
from app.agents.prompts.agent_memory_judge import AGENT_MEMORY_JUDGE_PROMPT

MemoryRelation = Literal["duplicate", "conflict", "complement", "unrelated"]


class MemoryVerdict(BaseModel):
    candidate_id: str
    relation: MemoryRelation
    merged_content: str | None = (
        None  # Requis uniquement si relation == "complement" : la règle fusionnée, une phrase unique couvrant le candidat ET le nouveau souvenir.
    )


memory_judge_agent = Agent(
    get_agent_model(),
    output_type=list[MemoryVerdict],
    system_prompt=AGENT_MEMORY_JUDGE_PROMPT,
    retries=2,
    model_settings=DETERMINISTIC_SETTINGS,
)


async def judge_candidates(
    new_trigger: str, new_content: str, candidates: list[dict]
) -> list[MemoryVerdict]:
    """
    Renvoie un ``MemoryVerdict`` par candidat, dans le même ordre. Liste vide si ``candidates`` est vide.
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
