"""The decisions a cheap backend can take on its own: one type label, one component.

Both are single-choice questions with adjudicated answers on dev, so a backend's accuracy
and calibration can be measured directly (E6) and gated on (the cascade, E7).
"""

from dataclasses import dataclass
from typing import Literal

from triagelab.data.profile import RepoProfile
from triagelab.eval.dataset import Gold
from triagelab.prompting import component_lines

QuestionId = Literal["type", "component"]


@dataclass(frozen=True)
class Question:
    id: QuestionId
    text: str
    options: tuple[str, ...]


def questions(profile: RepoProfile) -> dict[QuestionId, Question]:
    return {
        "type": Question(
            id="type",
            text="Which type label fits this issue? Exactly one applies.",
            options=tuple(profile.taxonomy.type),
        ),
        "component": Question(
            id="component",
            text=(
                "Which component would a fix for this issue change?\n"
                f"Components (each owns the files under its prefixes):\n{component_lines(profile)}"
            ),
            options=tuple(c.name for c in profile.components),
        ),
    }


def answer_for(qid: QuestionId, gold: Gold, profile: RepoProfile) -> str | None:
    """The reference answer to a question, or None when the labels don't settle it."""
    if qid == "type":
        types = [label for label in gold.labels if label in profile.taxonomy.type]
        return types[0] if len(types) == 1 else None
    return gold.component
