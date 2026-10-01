"""Several processes appending to one spend ledger lose nothing and corrupt nothing."""

import subprocess
import sys
from pathlib import Path

from triagelab.ledger import SpendLedger

WRITERS, PER_WRITER = 4, 50

# Plain subprocesses, not multiprocessing: on Windows a spawned worker re-imports the
# parent's `__main__`, which after the Streamlit app tests is the labeling app itself, so
# workers would re-run the app against whatever is in the local runs/ folder.
WRITER = """
import sys
from datetime import UTC, datetime
from pathlib import Path

from triagelab.ledger import SpendEntry, SpendLedger

path, writer, count = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
ledger = SpendLedger(Path(path))
for n in range(count):
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
"""


def test_parallel_writers_keep_every_entry(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    writers = [
        subprocess.Popen([sys.executable, "-c", WRITER, str(path), str(w), str(PER_WRITER)])
        for w in range(WRITERS)
    ]
    assert [w.wait(timeout=120) for w in writers] == [0] * WRITERS
    entries = SpendLedger(path).entries()  # raises on any corrupt line
    assert len(entries) == WRITERS * PER_WRITER
    for w in range(WRITERS):
        assert sorted(e.tokens_in for e in entries if e.run_id == f"writer-{w}") == list(
            range(PER_WRITER)
        )
