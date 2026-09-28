from datetime import UTC, datetime
from pathlib import Path

import pytest

from triagelab.ledger import SpendEntry, SpendLedger


def _entry(cost: float) -> SpendEntry:
    return SpendEntry(
        at=datetime(2026, 9, 29, tzinfo=UTC),
        run_id="r1",
        model="openai/gpt-6-luna",
        resolved_model="gpt-6-luna",
        tokens_in=10,
        tokens_out=5,
        cached_tokens_in=0,
        cost_usd=cost,
    )


def test_empty_ledger_totals_zero(tmp_path: Path) -> None:
    assert SpendLedger(tmp_path / "ledger.jsonl").total_usd() == 0.0


def test_total_sums_across_instances(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "ledger.jsonl"
    SpendLedger(path).record(_entry(0.25))
    SpendLedger(path).record(_entry(0.5))  # a later run, a fresh object
    assert SpendLedger(path).total_usd() == pytest.approx(0.75)
    assert len(SpendLedger(path).entries()) == 2
