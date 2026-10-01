"""Figures, regenerated from the run registry by code (AGENTS.md §16: never by hand)."""
# matplotlib types its plotting calls with untyped **kwargs; nothing else is relaxed.
# pyright: reportUnknownMemberType=false

from collections.abc import Mapping, Sequence
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless: CI runners and scripts have no display

import matplotlib.pyplot as plt  # after choosing the backend

from triagelab.eval.calibration import ece, reliability_bins, risk_coverage
from triagelab.eval.calibration_report import Outcome

_GREY = "#888888"


def _xy(rows: Sequence[Outcome]) -> tuple[list[float], list[bool]]:
    return [r.confidence for r in rows], [r.correct for r in rows]


def reliability_figure(series: Mapping[str, Sequence[Outcome]], title: str, path: Path) -> None:
    """One reliability diagram per source: accuracy per confidence bin vs the diagonal."""
    n = len(series)
    fig, axes = plt.subplots(1, n, figsize=(3.0 * n, 3.4), sharey=True, squeeze=False)
    for ax, (name, rows) in zip(axes[0], series.items(), strict=True):
        conf, right = _xy(rows)
        bins = reliability_bins(conf, right, 10, "width")
        ax.bar(
            [(b.lo + b.hi) / 2 for b in bins],
            [b.accuracy for b in bins],
            width=0.1,
            color="#4C72B0",
            alpha=0.75,
            edgecolor="white",
        )
        ax.plot([0, 1], [0, 1], linestyle="--", color=_GREY, linewidth=1)
        ax.scatter(
            [b.confidence for b in bins],
            [b.accuracy for b in bins],
            s=[8 + 2 * b.n for b in bins],
            color="#C44E52",
            zorder=3,
        )
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.set_xlabel("confidence")
        ax.set_title(f"{name}\nECE {ece(conf, right):.3f}, n={len(rows)}", fontsize=9)
    axes[0][0].set_ylabel("accuracy")
    fig.suptitle(title, fontsize=10)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    plt.close(fig)


def risk_coverage_figure(series: Mapping[str, Sequence[Outcome]], title: str, path: Path) -> None:
    """Accuracy of the most confident X% of answers, one line per source."""
    fig, ax = plt.subplots(figsize=(5.2, 3.8))
    for name, rows in series.items():
        points = risk_coverage(*_xy(rows))
        ax.step(
            [0.0, *(p.coverage for p in points)],
            [points[0].accuracy, *(p.accuracy for p in points)] if points else [0.0],
            where="post",
            label=name,
        )
    ax.set_xlim(0, 1)
    ax.set_xlabel("coverage (share of answers kept, most confident first)")
    ax.set_ylabel("accuracy of kept answers")
    ax.set_title(title, fontsize=10)
    ax.legend(fontsize=8, loc="lower left")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    plt.close(fig)
