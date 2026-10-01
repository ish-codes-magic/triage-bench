"""Typed decisions (AGENTS.md §11): one question, a typed answer, and a confidence.

A backend answers a question about an issue (`state`) without writing prose: it picks one
of a list of options, says yes or no, or gives a number in a range. The cascade gates on
the confidence, so *how* each backend computes it is what E6 compares.

Jev (TypeSafe AI) was meant to be one backend; the owner has no access (`jev_access: no`,
2026-10-01), so the backends are an LLM (two confidence methods) and a classifier. Any
future backend only has to implement this protocol.
"""

from collections.abc import Sequence
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    answer: str | bool | float
    confidence: float = Field(ge=0.0, le=1.0)
    backend: str
    cost_usd: float = 0.0  # at original prices: a cached answer reports what it cost
    latency_ms: int = 0
    # option -> probability, when the backend produces a distribution (logprobs, classifier)
    distribution: dict[str, float] = Field(default_factory=dict[str, float])


class DecisionError(Exception):
    """The backend can't answer this kind of question (e.g. a classifier with no head)."""


class DecisionBackend(Protocol):
    @property
    def name(self) -> str: ...

    def choose(self, state: str, question: str, options: Sequence[str]) -> Decision: ...

    def yes_no(self, state: str, question: str) -> Decision: ...

    def score(self, state: str, question: str, lo: float, hi: float) -> Decision: ...
