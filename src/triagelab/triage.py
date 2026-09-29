"""The triage contract: what every system under test returns (AGENTS.md §3).

Baselines, the agent and the cascade all implement `Triager`, so one scorer evaluates
them all and every comparison is like for like. Fields a system doesn't predict keep
their defaults (e.g. a classifier writes no triage comment).
"""

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from triagelab.data.models import IssueSnapshot


class TriageResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_ref: str
    # T1
    labels: list[str] = Field(default_factory=list[str])
    label_confidence: dict[str, float] = Field(default_factory=dict[str, float])
    # T3. `component_candidates` (ranked) extends §3 so top-3 accuracy is computable.
    component: str | None = None
    component_confidence: float | None = None
    component_candidates: list[str] = Field(default_factory=list[str])
    suggested_owners: list[str] = Field(default_factory=list[str])
    # T2. `duplicate_candidates` (ranked) extends §3 for Recall@k / MRR.
    duplicate_of: int | None = None
    duplicate_confidence: float | None = None
    duplicate_candidates: list[int] = Field(default_factory=list[int])
    # T4. `needs_info_confidence` extends §3 for calibration analysis (M7).
    needs_info: bool = False
    needs_info_confidence: float | None = None
    missing_info: list[str] = Field(default_factory=list[str])
    # T5
    triage_comment: str = ""
    # Provenance and system metrics
    decided_by: dict[str, str] = Field(default_factory=dict[str, str])
    run_id: str = ""
    trace_id: str = ""
    cost_usd: float = 0.0
    latency_ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    # Set when the system fell back (e.g. invalid model output); the fallback is still scored.
    error: str | None = None


class Triager(Protocol):
    """Anything that can triage one issue snapshot."""

    name: str

    def triage(self, issue: IssueSnapshot) -> TriageResult: ...
