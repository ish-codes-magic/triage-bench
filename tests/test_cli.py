from pathlib import Path

from typer.testing import CliRunner

from triagelab import __version__
from triagelab.cli import app

runner = CliRunner()
REPO_ROOT = Path(__file__).resolve().parents[1]
BASE = str(REPO_ROOT / "configs" / "base.yaml")


def test_help_lists_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("version", "config", "runs"):
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
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text(
        "name: t\nbudget: {usd_total: 150, usd_per_run: 5}\nllm: {model: m}\n"
        f"paths: {{runs_dir: {(tmp_path / 'runs').as_posix()}}}\n",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["runs", "list", "--config", str(cfg)])
    assert result.exit_code == 0
    assert "No runs yet." in result.output
    assert "All-time spend: $0.0000 of $150.00" in result.output
