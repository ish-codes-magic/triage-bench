"""Command-line entry point.

Kept deliberately thin: each command parses arguments, loads config, and calls one
function from the library. No business logic lives here, so everything the CLI does
is also reachable (and testable) from Python.
"""

from pathlib import Path
from typing import Annotated

import typer
import yaml

from triagelab import __version__
from triagelab.config import load_config
from triagelab.eval.registry import list_runs
from triagelab.ledger import SpendLedger

DEFAULT_CONFIG = Path("configs/base.yaml")
LEDGER_FILENAME = "spend_ledger.jsonl"

ConfigOpt = Annotated[Path, typer.Option("--config", "-c", help="Path to a YAML config.")]

app = typer.Typer(
    help="Eval-driven GitHub issue triage.",
    no_args_is_help=True,
    add_completion=False,
)
config_app = typer.Typer(help="Inspect configuration.", no_args_is_help=True)
runs_app = typer.Typer(help="Inspect the run registry.", no_args_is_help=True)
app.add_typer(config_app, name="config")
app.add_typer(runs_app, name="runs")


@app.callback()
def main() -> None:
    """Eval-driven GitHub issue triage."""


@app.command()
def version() -> None:
    """Print the installed triagelab version."""
    typer.echo(__version__)


@config_app.command("show")
def config_show(config: ConfigOpt = DEFAULT_CONFIG) -> None:
    """Print the fully resolved config (after `extends:` merging) and its fingerprint."""
    cfg = load_config(config)
    typer.echo(yaml.safe_dump(cfg.model_dump(mode="json"), sort_keys=False).rstrip())
    typer.echo(f"# fingerprint: {cfg.fingerprint()}")


@runs_app.command("list")
def runs_list(config: ConfigOpt = DEFAULT_CONFIG) -> None:
    """List past runs, newest first, with their cost and the all-time spend."""
    cfg = load_config(config)
    runs = list_runs(cfg.paths.runs_dir)
    if not runs:
        typer.echo("No runs yet.")
    for run in runs:
        cost = run.cost
        cost_text = (
            f"${cost.cost_usd:.4f}  calls={cost.calls} cache_hits={cost.cache_hits}"
            if cost
            else "(no cost recorded)"
        )
        typer.echo(f"{run.manifest.run_id}  {run.manifest.git_sha[:12]:<12}  {cost_text}")
    spent = SpendLedger(cfg.paths.runs_dir / LEDGER_FILENAME).total_usd()
    typer.echo(f"All-time spend: ${spent:.4f} of ${cfg.budget.usd_total:.2f}")
