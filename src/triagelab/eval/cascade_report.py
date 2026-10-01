"""The cascade report (E7): every gate's curve, its dev-chosen τ, and a paired comparison
with the full agent at that τ. Everything is recombined from stored runs."""

from pathlib import Path

from pydantic import BaseModel

from triagelab.data.profile import load_profile
from triagelab.decisions.cascade import (
    Cascade,
    CascadePoint,
    GateKind,
    agreement_signal,
    self_signal,
)
from triagelab.eval.bootstrap import paired_bootstrap
from triagelab.eval.report import Labels, examples_for, load_run
from triagelab.eval.score import METRICS, align, statistic
from triagelab.triage import TriageResult


class GateSpec(BaseModel):
    kind: GateKind
    run: str | None = None  # the decision-backend run, for an agreement gate


class CascadeSpec(BaseModel):
    title: str
    cheap: str
    full: str
    gates: dict[str, GateSpec]
    metrics: list[str]
    tolerance: float = 0.0  # how far below the full agent a τ may fall on dev


def _latest(runs_dir: Path, run: str) -> dict[str, TriageResult]:
    return {p.issue_ref: p for p in load_run(runs_dir / run)[2]}


def _fmt(p: CascadePoint, metrics: list[str]) -> str:
    cells = " | ".join(f"{p.metrics[m]:.3f}" for m in metrics)
    return f"{100 * p.escalated:.0f}% | {cells} | ${p.cost_per_1000:.2f}"


def build_cascade_report(
    spec: CascadeSpec, runs_dir: Path, labels: Labels, figures_dir: Path, stem: str
) -> str:
    from triagelab.eval.figures import cascade_figure

    cfg, split, _ = load_run(runs_dir / spec.cheap)
    examples = examples_for(cfg, split, labels)
    types = load_profile(cfg.dataset.profile).taxonomy.type
    cheap, full = _latest(runs_dir, spec.cheap), _latest(runs_dir, spec.full)
    curves: dict[str, list[CascadePoint]] = {}
    rows: list[str] = []
    deltas: list[str] = []
    references: dict[str, CascadePoint] = {}
    for name, gate in spec.gates.items():
        if gate.kind == "self":
            signal = {r: self_signal(p, types) for r, p in cheap.items()}
            gate_cost: dict[str, float] = {}
        else:
            assert gate.run is not None, f"gate {name!r} needs a run"
            backend = _latest(runs_dir, gate.run)
            signal = {
                r: agreement_signal(p, backend[r], types) for r, p in cheap.items() if r in backend
            }
            gate_cost = {r: p.cost_usd for r, p in backend.items()}
        c = Cascade(examples, cheap, full, signal, gate_cost, spec.metrics)
        if not references:
            # Reference points: each tier alone, over the same issues, at its own cost.
            for tier, preds in (("cheap tier alone", cheap), ("full agent alone", full)):
                alone = Cascade(c.examples, preds, preds, dict.fromkeys(c.refs(), 1.0), {},
                                spec.metrics).point(0.0)  # fmt: skip
                references[tier] = alone
        curves[name] = c.curve()
        tau = c.choose_tau(c.examples, spec.tolerance)
        chosen = c.point(tau)
        taus, crossed = c.cross_fitted(spec.tolerance)
        rows.append(f"| {name} | {tau:.3f} | {_fmt(chosen, spec.metrics)} |")
        rows.append(
            f"| {name}, cross-fitted (τ {', '.join(f'{t:.2f}' for t in taus)}) | | "
            f"{_fmt(crossed, spec.metrics)} |"
        )
        a = align(c.examples, [full[r] for r in c.refs()])
        b = align(c.examples, c.combined(tau, c.refs()))
        for m in spec.metrics:
            d = paired_bootstrap(
                len(c.examples), statistic(METRICS[m], a), statistic(METRICS[m], b)
            )
            flag = " (significant)" if d.significant else ""
            deltas.append(f"| {name} | {m} | {d.delta:+.3f} [{d.low:+.3f}, {d.high:+.3f}]{flag} |")
    figure = figures_dir / f"{stem}-{labels}-cascade.png"
    cascade_figure(curves, references, spec.metrics, f"{spec.title} ({labels} labels)", figure)
    head = " | ".join(spec.metrics)
    lines = [
        f"# {spec.title} ({labels} labels)",
        "",
        f"Cheap tier `{spec.cheap}`; full agent `{spec.full}`; n = {len(examples)} issues. "
        f"τ is the cheapest threshold whose {', '.join(spec.metrics)} stay within "
        f"{spec.tolerance} of the full agent's on dev.",
        "",
        f"| system | τ | escalated | {head} | cost / 1,000 issues |",
        "|---|---|---|" + "---|" * len(spec.metrics) + "---|",
        *(f"| {name} | | {_fmt(p, spec.metrics)} |" for name, p in references.items()),
        *rows,
        "",
        "Cascade at the chosen τ minus the full agent (paired bootstrap, 1,000 resamples):",
        "",
        "| gate | metric | Δ [95% CI] |",
        "|---|---|---|",
        *deltas,
        "",
        f"![cascade curve](../figures/{figure.name})",
        "",
        "Cross-fitted rows route each issue by the τ chosen on the other half of dev, so they "
        "estimate what the chosen τ does on unseen issues.",
    ]
    return "\n".join(lines) + "\n"
