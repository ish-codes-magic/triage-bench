"""Pricing, cost accounting and the budget hard stop.

Everything here is pure: no network, no clock, no files except `load_price_table`.
That keeps the money logic trivially testable with hand-computed numbers.
"""

import threading
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

_PER_MTOK = 1_000_000


class ModelPrice(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    input_per_mtok: float = Field(ge=0)
    output_per_mtok: float = Field(ge=0)
    cached_input_per_mtok: float | None = Field(default=None, ge=0)
    source: str
    verified_on: date
    notes: str | None = None


class UnknownModelPriceError(KeyError):
    """Raised for a model with no price entry. We refuse to spend money we can't count."""


class PriceTable(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    models: dict[str, ModelPrice]

    def price_for(self, model: str) -> ModelPrice:
        try:
            return self.models[model]
        except KeyError:
            raise UnknownModelPriceError(
                f"No price for {model!r}. Add a verified entry to configs/prices.yaml."
            ) from None


def load_price_table(path: Path) -> PriceTable:
    raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    return PriceTable.model_validate(raw)


class Usage(BaseModel):
    """Token counts for one model call.

    `tokens_in` is the total prompt size *including* any tokens served from the provider's
    prompt cache; `cached_tokens_in` is the part of it billed at the cached rate.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    tokens_in: int = Field(ge=0)
    tokens_out: int = Field(ge=0)
    cached_tokens_in: int = Field(default=0, ge=0)
    # Hidden "thinking" tokens: already included in tokens_out (and billed), kept separately
    # so the cost of reasoning can be measured.
    reasoning_tokens: int = Field(default=0, ge=0)


def cost_usd(usage: Usage, price: ModelPrice) -> float:
    """Exact cost of a completed call."""
    cached = min(usage.cached_tokens_in, usage.tokens_in)
    uncached = usage.tokens_in - cached
    cached_rate = (
        price.cached_input_per_mtok
        if price.cached_input_per_mtok is not None
        else price.input_per_mtok
    )
    return (
        uncached * price.input_per_mtok
        + cached * cached_rate
        + usage.tokens_out * price.output_per_mtok
    ) / _PER_MTOK


def worst_case_cost_usd(prompt_tokens: int, max_tokens: int, price: ModelPrice) -> float:
    """Upper bound on a call's cost *before* it is made.

    The model cannot emit more than `max_tokens`, so assuming the full output budget and
    no cache discount gives a real ceiling. Only `prompt_tokens` is an estimate.
    """
    return (prompt_tokens * price.input_per_mtok + max_tokens * price.output_per_mtok) / _PER_MTOK


class BudgetExceededError(RuntimeError):
    """Raised *before* a call whose worst-case cost would break a budget."""


class BudgetGuard:
    """Enforces the per-run and all-time budgets as a hard stop, safely under concurrency.

    Before a call, `reserve` claims its worst-case cost; after it, `settle` swaps that
    reservation for the actual cost (or `release` returns it if the call failed).
    Reserving, rather than merely checking, matters with parallel calls: eight threads
    that all "check" before any has been charged could together overshoot the cap.
    """

    def __init__(self, *, per_run_usd: float, total_usd: float, spent_before_run_usd: float):
        self._per_run_usd = per_run_usd
        self._total_usd = total_usd
        self._spent_before_run_usd = spent_before_run_usd
        self._spent_run_usd = 0.0
        self._reserved_usd = 0.0
        self._lock = threading.Lock()

    @property
    def spent_run_usd(self) -> float:
        return self._spent_run_usd

    @property
    def remaining_run_usd(self) -> float:
        committed = self._spent_run_usd + self._reserved_usd
        run_room = self._per_run_usd - committed
        total_room = self._total_usd - self._spent_before_run_usd - committed
        return max(0.0, min(run_room, total_room))

    def reserve(self, projected_usd: float) -> None:
        with self._lock:
            if projected_usd > self.remaining_run_usd:
                raise BudgetExceededError(
                    f"Refusing call: worst case ${projected_usd:.4f} exceeds remaining budget "
                    f"${self.remaining_run_usd:.4f} (run cap ${self._per_run_usd:.2f}, "
                    f"total cap ${self._total_usd:.2f}, spent before this run "
                    f"${self._spent_before_run_usd:.2f})."
                )
            self._reserved_usd += projected_usd

    def settle(self, projected_usd: float, actual_usd: float) -> None:
        with self._lock:
            self._reserved_usd -= projected_usd
            self._spent_run_usd += actual_usd

    def release(self, projected_usd: float) -> None:
        with self._lock:
            self._reserved_usd -= projected_usd
