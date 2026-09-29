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
retrieval_app = typer.Typer(help="Build and evaluate the retrieval index.", no_args_is_help=True)
mcp_app = typer.Typer(help="Run the repo-intel MCP server.", no_args_is_help=True)
app.add_typer(config_app, name="config")
app.add_typer(data_app, name="data")
app.add_typer(retrieval_app, name="retrieval")
app.add_typer(mcp_app, name="mcp")
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


@runs_app.command("stats")
def runs_stats(
    run_dir: Annotated[Path, typer.Argument(help="A run folder, e.g. runs/<run_id>.")],
    out: Annotated[Path | None, typer.Option("--out", help="Also write the report here.")] = None,
) -> None:
    """Agent system metrics from a run's traces: steps, tools, skills, budgets, cost."""
    from triagelab.harness.trace_stats import agent_stats, render

    text = render(agent_stats(run_dir), run_dir.name)
    typer.echo(text)
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(text.encode("utf-8"))


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
        reasoning=cfg.llm.reasoning,
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
def data_collect(
    profile: ProfileOpt,
    data_dir: DataDirOpt = Path("data"),
    index_history: Annotated[
        bool, typer.Option("--index-history", help="Collect retrieval-only history (index_start).")
    ] = False,
) -> None:
    """Collect a repo's issue histories and fixing-PR files (resumable, rate-limit aware)."""
    from triagelab.data.collect import collect_index_history, collect_repo
    from triagelab.data.github import GraphQLClient
    from triagelab.data.profile import load_profile

    load_dotenv()
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        typer.echo("GITHUB_TOKEN is not set (see .env.example).", err=True)
        raise typer.Exit(code=2)
    client = GraphQLClient(token, retry=RetryConfig(max_attempts=5, max_delay_s=60))
    repo_profile = load_profile(profile)
    if index_history:
        found, new, missing = collect_index_history(client, repo_profile, data_dir, log=typer.echo)
        typer.echo(f"index history: {found} found, {new} new, {missing} missing")
        return
    summary = collect_repo(client, repo_profile, data_dir, log=typer.echo)
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


@app.command("eval")
def eval_cmd(
    config: Annotated[Path, typer.Option("--config", "-c", help="Experiment config YAML.")],
    split: Annotated[str, typer.Option(help="dev | test | train")] = "dev",
    limit: Annotated[int | None, typer.Option(help="Only the first N issues.")] = None,
    allow_test: Annotated[
        bool, typer.Option("--allow-test", help="Unlock the test split (max twice, logged).")
    ] = False,
    resume: Annotated[Path | None, typer.Option(help="Continue this run folder.")] = None,
) -> None:
    """Run an experiment on a split and print its scorecard (with 95% bootstrap CIs)."""
    from triagelab.data.splits import parse_split
    from triagelab.eval.runner import TestSetLockedError, run_eval

    try:
        split_name = parse_split(split)
    except ValueError as err:
        raise typer.BadParameter(str(err)) from err
    load_dotenv()
    cfg = load_config(config)
    try:
        outcome = run_eval(
            cfg,
            split=split_name,
            runs_dir=cfg.paths.runs_dir,
            command=f"eval --config {config.as_posix()} --split {split}",
            log=typer.echo,
            limit=limit,
            allow_test=allow_test,
            resume_dir=resume,
        )
    except TestSetLockedError as err:
        typer.echo(str(err), err=True)
        raise typer.Exit(code=3) from err
    typer.echo(f"run {outcome.run_id}: {outcome.completed}/{outcome.total} issues")
    if outcome.stopped_reason:
        typer.echo(f"stopped: {outcome.stopped_reason}", err=True)
        typer.echo(f"resume with: --resume {outcome.run_dir.as_posix()}", err=True)
        raise typer.Exit(code=2)
    card = outcome.scorecard
    assert card is not None
    for name, m in card.metrics.items():
        point = "n/a" if m.point is None else f"{m.point:.3f} [{m.low:.3f}, {m.high:.3f}]"
        weighted = "n/a" if m.weighted is None else f"{m.weighted:.3f}"
        typer.echo(f"  {name:20} {point:26} natural-rate: {weighted}")
    s = card.system
    typer.echo(
        # What the answers cost to produce, and what this run paid (0 if all cached).
        f"  answers cost ${s.cost_usd_total:.4f} (${s.cost_usd_per_issue:.5f}/issue), "
        f"spent this run ${outcome.spent_usd:.4f} | "
        f"p50 {s.latency_ms_p50 / 1000:.1f}s p95 {s.latency_ms_p95 / 1000:.1f}s | errors {s.errors}"
    )


@app.command()
def compare(
    run_a: Path,
    run_b: Path,
    exclude_errors: Annotated[
        bool, typer.Option("--exclude-errors", help="Skip issues where either run fell back.")
    ] = False,
) -> None:
    """Paired-bootstrap comparison of two runs (B - A) on the issues both predicted."""
    from triagelab.eval.report import compare_runs, render_comparison

    rows = compare_runs(run_a, run_b, exclude_errors=exclude_errors)
    typer.echo(render_comparison(rows, run_a.name, run_b.name))


@app.command()
def results(
    split: str = "dev",
    config: ConfigOpt = DEFAULT_CONFIG,
    out_dir: Annotated[Path, typer.Option("--out-dir")] = Path("reports/results"),
) -> None:
    """Write the results table (latest run per experiment) to reports/results/<split>.md."""
    from triagelab.eval.report import load_scored_runs, results_table

    cfg = load_config(config)
    table = results_table(load_scored_runs(cfg.paths.runs_dir), split)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{split}.md"
    heading = f"# Results: {split} split"
    out.write_bytes("\n\n".join([heading, table]).encode("utf-8"))
    typer.echo(table)
    typer.echo(f"written to {out.as_posix()}")


@data_app.command("checkout")
def data_checkout(profile: ProfileOpt, data_dir: DataDirOpt = Path("data")) -> None:
    """Download the source tree as of the last main-branch commit before eval_start."""
    from triagelab.data.checkout import download_checkout
    from triagelab.data.profile import load_profile

    load_dotenv()
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        typer.echo("GITHUB_TOKEN is not set (see .env.example).", err=True)
        raise typer.Exit(code=2)
    info = download_checkout(load_profile(profile), data_dir, token)
    typer.echo(f"checkout {info.repo}@{info.commit[:10]} ({info.committed_at:%Y-%m-%d %H:%M} UTC)")


@retrieval_app.command("build")
def retrieval_build(
    profile: ProfileOpt,
    data_dir: DataDirOpt = Path("data"),
    dense: Annotated[bool, typer.Option("--dense/--no-dense")] = True,
) -> None:
    """Build the time-aware corpus and (resumably) embed it for dense retrieval."""
    from triagelab.data.profile import load_profile
    from triagelab.retrieval.embeddings import embed_corpus, store_dir
    from triagelab.retrieval.index import build_corpus_from_raw, corpus_path, index_dir, write_meta

    repo_profile = load_profile(profile)
    corpus = build_corpus_from_raw(data_dir, repo_profile)
    corpus.save(corpus_path(data_dir, repo_profile))
    typer.echo(f"corpus: {len(corpus)} issues")
    meta: dict[str, object] = {"documents": len(corpus)}
    if dense:
        from triagelab.retrieval.encoders import FastEmbedEncoder

        encoder = FastEmbedEncoder()
        added = embed_corpus(
            corpus,
            encoder,
            store_dir(index_dir(data_dir, repo_profile), encoder.name),
            log=typer.echo,
        )
        meta |= {"encoder": encoder.name, "embedded_now": added}
    write_meta(data_dir, repo_profile, meta)


@retrieval_app.command("eval")
def retrieval_eval(
    profile: ProfileOpt,
    data_dir: DataDirOpt = Path("data"),
    dense: Annotated[bool, typer.Option("--dense/--no-dense")] = True,
    query_prefix: Annotated[
        bool, typer.Option("--query-prefix/--no-query-prefix", help="arctic-embed query prefix.")
    ] = False,
    out_dir: Annotated[Path, typer.Option("--out-dir")] = Path("reports/retrieval"),
) -> None:
    """Recall@k and MRR for finding duplicates' originals (train/dev windows only)."""
    from triagelab.data.profile import load_profile
    from triagelab.retrieval.dense import Encoder
    from triagelab.retrieval.evaluate import compare_all, duplicate_queries, rank, render, score
    from triagelab.retrieval.index import load_searcher

    repo_profile = load_profile(profile)
    encoder: Encoder | None = None
    notes: list[str] = []
    if dense:
        from triagelab.retrieval.encoders import ARCTIC_QUERY_PREFIX, FastEmbedEncoder

        encoder = FastEmbedEncoder(query_prefix=ARCTIC_QUERY_PREFIX if query_prefix else "")
        prefix = f'`"{ARCTIC_QUERY_PREFIX.strip()}"`' if query_prefix else "none"
        notes.append(f"Dense encoder: `{encoder.name}`; query prefix: {prefix}.")
    searcher = load_searcher(data_dir, repo_profile, encoder=encoder)
    queries = duplicate_queries(data_dir, repo_profile)
    rankings = [rank(searcher, queries, mode=mode) for mode in searcher.modes]
    text = render(
        [score(r) for r in rankings],
        repo_profile.repo,
        comparisons=compare_all(rankings),
        notes=notes,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    # The prefix ablation gets its own file so both reports stay regenerable side by side.
    out = out_dir / f"{repo_profile.slug}{'-query-prefix' if dense and query_prefix else ''}.md"
    out.write_bytes(text.encode("utf-8"))
    typer.echo(text)
    typer.echo(f"written to {out.as_posix()}")


@mcp_app.command("serve")
def mcp_serve(
    profile: ProfileOpt,
    data_dir: DataDirOpt = Path("data"),
    dense: Annotated[bool, typer.Option("--dense/--no-dense")] = True,
) -> None:
    """Serve repo-intel over stdio (for MCP clients and the MCP Inspector)."""
    from triagelab.mcp_server.app import main as serve

    serve(
        ["--profile", str(profile), "--data-dir", str(data_dir), *([] if dense else ["--no-dense"])]
    )
