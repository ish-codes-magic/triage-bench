"""The issue-level cascade, live (M9): what `decisions/cascade.py` evaluates offline.

    cheap tier triages the issue
    signal = its own confidence: min(type-label confidence, component confidence)
    signal >= tau  -> its answer stands
    signal <  tau  -> the full agent triages the issue, and its answer is returned

The offline module recombines stored runs to *choose* tau on dev; this one applies a
chosen tau to one issue at a time, which is what a deployment (and the demo) needs. Both
use the same `self_signal`, so on the same answers they route identically, and a test
holds them to that. An escalated issue pays for both tiers.
"""

import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from pydantic import BaseModel

from triagelab.data.models import IssueSnapshot
from triagelab.data.storage import append_jsonl
from triagelab.decisions.cascade import self_signal
from triagelab.triage import Triager, TriageResult

ROUTES_FILE = "cascade.jsonl"


class Routing(BaseModel):
    """Why one issue went where it went: the record behind `decided_by["cascade"]`."""

    issue_ref: str
    signal: float
    tau: float
    escalated: bool
    cheap_trace_id: str
    full_trace_id: str | None = None


class CascadeTriager:
    name = "cascade"

    def __init__(
        self,
        cheap: Triager,
        full: Triager,
        types: Sequence[str],
        tau: float,
        on_routing: Callable[[Routing], None] | None = None,
    ) -> None:
        self._cheap = cheap
        self._full = full
        self._types = list(types)
        self._tau = tau
        self._on_routing = on_routing

    def triage(self, issue: IssueSnapshot) -> TriageResult:
        started = time.perf_counter()
        cheap = self._cheap.triage(issue)
        signal = self_signal(cheap, self._types)  # 0 for a fallback, so those always escalate
        escalated = signal < self._tau
        full = self._full.triage(issue) if escalated else None
        if self._on_routing is not None:
            self._on_routing(
                Routing(
                    issue_ref=issue.issue_ref,
                    signal=signal,
                    tau=self._tau,
                    escalated=escalated,
                    cheap_trace_id=cheap.trace_id,
                    full_trace_id=full.trace_id if full else None,
                )
            )
        latency = round((time.perf_counter() - started) * 1000)
        if full is None:
            kept = {**cheap.decided_by, "cascade": "cheap tier"}
            return cheap.model_copy(update={"decided_by": kept, "latency_ms": latency})
        return full.model_copy(
            update={
                "decided_by": {**full.decided_by, "cascade": "escalated"},
                "cost_usd": cheap.cost_usd + full.cost_usd,
                "tokens_in": cheap.tokens_in + full.tokens_in,
                "tokens_out": cheap.tokens_out + full.tokens_out,
                "latency_ms": latency,
            }
        )


def routing_log(run_dir: Path) -> Callable[[Routing], None]:
    """Append each routing to the run's `cascade.jsonl` (the runner calls from threads)."""
    lock = threading.Lock()

    def write(routing: Routing) -> None:
        with lock:
            append_jsonl(run_dir / ROUTES_FILE, [routing])

    return write
