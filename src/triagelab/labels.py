"""Post-processing shared by every LLM labeller (the single-shot baseline and the agent)."""

from collections.abc import Collection, Iterable
from typing import Protocol


class Guess(Protocol):
    @property
    def label(self) -> str: ...
    @property
    def confidence(self) -> float: ...


def confident[G: Guess](guesses: Iterable[G], family: Collection[str], floor: float) -> list[G]:
    """Drop topic/OS ("family") labels given less than `floor` confidence (iteration 8).

    Type and area labels are kept whatever their confidence: on dev they were nearly
    always given >= 0.9, while topic/OS labels under 0.95 were right 3 times in 44.
    """
    return [g for g in guesses if g.label not in family or g.confidence >= floor]
