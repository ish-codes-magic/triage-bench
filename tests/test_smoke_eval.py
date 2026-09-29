"""Evals as tests: on the synthetic smoke dataset the classifier must beat majority."""

from pathlib import Path

from triagelab.config import load_config
from triagelab.eval.runner import run_eval

from .smoke_dataset import write_smoke_dataset


def test_classifier_beats_majority_on_the_smoke_dataset(tmp_path: Path) -> None:
    configs = write_smoke_dataset(tmp_path)
    scores = {}
    for kind in ("majority", "classifier"):
        cfg = load_config(configs[kind])
        outcome = run_eval(
            cfg, split="dev", runs_dir=cfg.paths.runs_dir, command="t", log=lambda _: None
        )
        assert outcome.scorecard is not None
        scores[kind] = outcome.scorecard.metrics
    for metric in ("t1_micro_f1", "t3_accuracy"):
        clf, maj = scores["classifier"][metric], scores["majority"][metric]
        assert clf.point is not None
        assert maj.high is not None
        assert clf.point > maj.high, metric  # beats majority's whole interval, not just its point
