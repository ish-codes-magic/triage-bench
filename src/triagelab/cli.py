"""Command-line entry point.

Kept deliberately thin: each command parses arguments, loads config, and calls one
function from the library. No business logic lives here, so everything the CLI does
is also reachable (and testable) from Python.
"""

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict

from triagelab import __version__, wiring
from triagelab.config import RetryConfig, load_config
from triagelab.cost import BudgetExceededError
from triagelab.eval.registry import create_run, git_info, list_runs, write_cost
from triagelab.ledger import SpendLedger
from triagelab.llm_client import LLMRequest, Message

DEFAULT_CONFIG = Path("configs/base.yaml")

ConfigOpt = Annotated[Path, typer.Option("--config", "-c", help="Path to a YAML config.")]

app = typer.Typer(
    help="Eval-driven GitHub issue triage.",
    no_args_is_help=True,
    add_completion=False,
)
config_app = typer.Typer(help="Inspect configuration.", no_args_is_help=True)
runs_app = typer.Typer(help="Inspect the run registry.", no_args_is_help=True)
llm_app = typer.Typer(help="Talk to models through the cached, budgeted client.")
data_app = typer.Typer(help="Collect and prepare datasets.", no_args_is_help=True)
app.add_typer(config_app, name="config")
app.add_typer(data_app, name="data")
app.add_typer(runs_app, name="runs")
app.add_typer(llm_app, name="llm", no_args_is_help=True)


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
            f"${cost.cost_usd:.6f}  calls={cost.calls} cache_hits={cost.cache_hits}"
            if cost
            else "(no cost recorded)"
        )
        typer.echo(f"{run.manifest.run_id}  {run.manifest.git_sha[:12]:<12}  {cost_text}")
    spent = SpendLedger(cfg.paths.ledger_file).total_usd()
    typer.echo(f"All-time spend: ${spent:.6f} of ${cfg.budget.usd_total:.2f}")


class Pong(BaseModel):
    """The schema `llm ping` asks for, so the smoke test exercises structured output too."""

    model_config = ConfigDict(extra="forbid")  # emits additionalProperties: false (strict mode)

    reply: str


PING_PROMPT = 'This is a connectivity check. Respond with the JSON object {"reply": "pong"}.'


@llm_app.command("ping")
def llm_ping(
    config: ConfigOpt = DEFAULT_CONFIG,
    model: Annotated[str | None, typer.Option(help="Override llm.model for this call.")] = None,
) -> None:
    """Make one structured model call through the full stack and record it as a run.

    Run it twice: the second call is served from the cache and costs $0.
    """
    load_dotenv()  # API keys live in .env (gitignored), never in config
    cfg = load_config(config)
    if model is not None:
        cfg = cfg.model_copy(update={"llm": cfg.llm.model_copy(update={"model": model})})

    run_dir, manifest = create_run(
        cfg,
        runs_dir=cfg.paths.runs_dir,
        command="llm ping",
        now=datetime.now(UTC),
        git=git_info(Path.cwd()),
    )
    client = wiring.build_llm_client(cfg, run_id=manifest.run_id)
    request = LLMRequest(
        model=cfg.llm.model,
        route=cfg.llm.route,
        messages=(Message(role="user", content=PING_PROMPT),),
        max_tokens=cfg.llm.max_tokens,
        temperature=cfg.llm.temperature,
        seed=cfg.llm.seed,
    )
    try:
        pong, response = client.complete_structured(request, Pong)
    except BudgetExceededError as err:
        typer.echo(f"Budget stop: {err}", err=True)
        raise typer.Exit(code=2) from err
    finally:
        write_cost(run_dir, client.stats)  # every run records its cost, even a failed one

    source = "cache hit" if response.cache_hit else "live call"
    spent_total = SpendLedger(cfg.paths.ledger_file).total_usd()
    typer.echo(f"run       {manifest.run_id}")
    route = f" @ {cfg.llm.route.tag}" if cfg.llm.route else ""
    typer.echo(f"model     {response.model}{route} -> {response.resolved_model or 'unknown'}")
    typer.echo(f"reply     {pong.reply}")
    typer.echo(f"tokens    in={response.usage.tokens_in} out={response.usage.tokens_out}")
    typer.echo(
        f"cost      ${response.cost_usd:.6f} ({source}; "
        f"originally ${response.original_cost_usd:.6f})"
    )
    typer.echo(f"latency   {response.latency_ms} ms")
    typer.echo(f"spend     all-time ${spent_total:.6f} of ${cfg.budget.usd_total:.2f}")


ProfileOpt = Annotated[
    Path, typer.Option("--profile", "-p", help="Repo profile YAML (configs/repos/...).")
]
DataDirOpt = Annotated[Path, typer.Option("--data-dir", help="Root of the local dataset.")]


@data_app.command("collect")
def data_collect(profile: ProfileOpt, data_dir: DataDirOpt = Path("data")) -> None:
    """Collect a repo's issue histories and fixing-PR files (resumable, rate-limit aware)."""
    from triagelab.data.collect import collect_repo
    from triagelab.data.github import GraphQLClient
    from triagelab.data.profile import load_profile

    load_dotenv()
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        typer.echo("GITHUB_TOKEN is not set (see .env.example).", err=True)
        raise typer.Exit(code=2)
    client = GraphQLClient(token, retry=RetryConfig(max_attempts=5, max_delay_s=60))
    summary = collect_repo(client, load_profile(profile), data_dir, log=typer.echo)
    typer.echo(summary.model_dump_json(indent=2))


@data_app.command("build")
def data_build(
    profile: ProfileOpt,
    data_dir: DataDirOpt = Path("data"),
    reports_dir: Annotated[Path, typer.Option("--reports-dir")] = Path("reports"),
) -> None:
    """Build snapshots, silver labels, splits and the dataset report from raw data."""
    from triagelab.data.build import build_dataset
    from triagelab.data.profile import load_profile

    paths = build_dataset(load_profile(profile), data_dir, reports_dir)
    for name, path in paths.model_dump().items():
        typer.echo(f"{name:12} {Path(path).as_posix()}")
