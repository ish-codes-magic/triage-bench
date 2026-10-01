"""Several processes appending to one spend ledger lose nothing and corrupt nothing."""

from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from triagelab.ledger import SpendEntry, SpendLedger

WRITERS, PER_WRITER = 4, 50


def write_many(args: tuple[str, int]) -> None:
    path, writer = args
    ledger = SpendLedger(Path(path))
    for n in range(PER_WRITER):
        ledger.record(
            SpendEntry(
                at=datetime.now(UTC),
                run_id=f"writer-{writer}",
                model="m",
                resolved_model=None,
                tokens_in=n,
                tokens_out=1,
                cached_tokens_in=0,
                cost_usd=0.001,
                # Different lengths per writer, like the entries that collided in M6.
                litellm_cost_usd=0.000123456789 * (writer + 1),
            )
        )


def test_parallel_writers_keep_every_entry(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    with ProcessPoolExecutor(WRITERS) as pool:
        list(pool.map(write_many, [(str(path), w) for w in range(WRITERS)]))
    entries = SpendLedger(path).entries()  # raises on any corrupt line
    assert len(entries) == WRITERS * PER_WRITER
    for w in range(WRITERS):
        assert sorted(e.tokens_in for e in entries if e.run_id == f"writer-{w}") == list(
            range(PER_WRITER)
        )
