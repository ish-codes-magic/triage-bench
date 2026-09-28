from pathlib import Path

import pytest
from typer.testing import CliRunner

from triagelab import __version__, wiring
from triagelab.cli import app
from triagelab.config import Config
from triagelab.ledger import SpendLedger
from triagelab.llm_client import LLMClient

from .fakes import FakeBackend

runner = CliRunner()
REPO_ROOT = Path(__file__).resolve().parents[1]
BASE = str(REPO_ROOT / "configs" / "base.yaml")


def _tmp_config(tmp_path: Path, per_run_usd: float = 5.0) -> Path:
    """A config whose runs, cache and ledger all live under tmp_path."""
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text(
        f"name: cli-test\n"
        f"budget: {{usd_total: 150, usd_per_run: {per_run_usd}}}\n"
        f"llm: {{model: openai/gpt-6-luna, max_tokens: 64}}\n"
        f"cache: {{dir: {(tmp_path / 'cache').as_posix()}}}\n"
        f"paths:\n"
        f"  runs_dir: {(tmp_path / 'runs').as_posix()}\n"
        f"  ledger_file: {(tmp_path / 'runs' / 'ledger.jsonl').as_posix()}\n"
        f"  prices_file: {(REPO_ROOT / 'configs' / 'prices.yaml').as_posix()}\n",
        encoding="utf-8",
    )
    return cfg


@pytest.fixture
def fake_backend(monkeypatch: pytest.MonkeyPatch) -> FakeBackend:
    """Route the CLI's model calls to a fake backend: offline and free."""
    backend = FakeBackend(text='{"reply": "pong"}')
    real_build = wiring.build_llm_client

    def build(cfg: Config, *, run_id: str) -> LLMClient:
        return real_build(cfg, run_id=run_id, backend=backend)

    monkeypatch.setattr(wiring, "build_llm_client", build)
    return backend


def test_help_lists_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("version", "config", "runs", "llm"):
        assert command in result.output


def test_version_prints_package_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.output.strip() == __version__


def test_config_show_prints_resolved_config_and_fingerprint() -> None:
    result = runner.invoke(app, ["config", "show", "--config", BASE])
    assert result.exit_code == 0
    assert "name: base" in result.output
    assert "# fingerprint: " in result.output


def test_runs_list_with_empty_registry(tmp_path: Path) -> None:
    result = runner.invoke(app, ["runs", "list", "--config", str(_tmp_config(tmp_path))])
    assert result.exit_code == 0
    assert "No runs yet." in result.output
    assert "All-time spend: $0.000000 of $150.00" in result.output


def test_llm_ping_twice_second_is_a_free_cache_hit(
    tmp_path: Path, fake_backend: FakeBackend
) -> None:
    cfg = str(_tmp_config(tmp_path))
    first = runner.invoke(app, ["llm", "ping", "--config", cfg])
    second = runner.invoke(app, ["llm", "ping", "--config", cfg])

    assert first.exit_code == 0, first.output
    assert "reply     pong" in first.output
    assert "live call" in first.output
    assert second.exit_code == 0, second.output
    assert "cache hit" in second.output
    assert "$0.000000" in second.output
    assert fake_backend.calls == 1
    # 1000 in * $0.10/M + 100 out * $0.50/M = $0.00015, logged exactly once
    assert SpendLedger(tmp_path / "runs" / "ledger.jsonl").total_usd() == pytest.approx(0.00015)

    listing = runner.invoke(app, ["runs", "list", "--config", cfg])
    assert listing.output.count("cli-test") == 2


def test_llm_ping_budget_stop_exits_2(tmp_path: Path, fake_backend: FakeBackend) -> None:
    result = runner.invoke(
        app, ["llm", "ping", "--config", str(_tmp_config(tmp_path, per_run_usd=1e-9))]
    )
    assert result.exit_code == 2
    assert fake_backend.calls == 0
    run_dirs = [p for p in (tmp_path / "runs").iterdir() if p.is_dir()]
    assert (run_dirs[0] / "cost.json").is_file()  # a stopped run still records its cost
