"""Command-line entry point.

Kept deliberately thin: each command parses arguments, loads config, and calls one
function from the library. No business logic lives here, so everything the CLI does
is also reachable (and testable) from Python.
"""

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

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
judge_app = typer.Typer(help="Sample and calibrate the T5 comment judge.", no_args_is_help=True)
skills_app = typer.Typer(help="Build Agent Skills.", no_args_is_help=True)
failures_app = typer.Typer(help="Tag failures and validate the tagger.", no_args_is_help=True)
gate_app = typer.Typer(help="The CI regression gate (eval.yml).", no_args_is_help=True)
annotate_app = typer.Typer(
    help="Export annotation batches as files and import the answers (ADR-0035).",
    no_args_is_help=True,
)
app.add_typer(config_app, name="config")
app.add_typer(data_app, name="data")
app.add_typer(retrieval_app, name="retrieval")
app.add_typer(mcp_app, name="mcp")
app.add_typer(judge_app, name="judge")
app.add_typer(skills_app, name="skills")
app.add_typer(failures_app, name="failures")
app.add_typer(gate_app, name="gate")
app.add_typer(annotate_app, name="annotate")
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
    otlp_endpoint: Annotated[
        str | None,
        typer.Option(
            "--otlp-endpoint",
            envvar="TRIAGELAB_OTLP_ENDPOINT",
            help="Also export agent traces here, e.g. http://localhost:6006/v1/traces.",
        ),
    ] = None,
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
    if otlp_endpoint:  # a viewing concern: it changes no model request or result
        tracing = cfg.tracing.model_copy(update={"otlp_endpoint": otlp_endpoint})
        cfg = cfg.model_copy(update={"tracing": tracing})
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
    labels: Annotated[str, typer.Option(help="silver | gold (adjudicated issues only)")] = "silver",
) -> None:
    """Paired-bootstrap comparison of two runs (B - A) on the issues both predicted."""
    from triagelab.eval.report import compare_runs, render_comparison

    if labels not in ("silver", "gold"):
        raise typer.BadParameter("labels must be silver or gold")
    rows = compare_runs(run_a, run_b, exclude_errors=exclude_errors, labels=labels)
    typer.echo(render_comparison(rows, run_a.name, run_b.name))


@app.command()
def results(
    split: str = "dev",
    config: ConfigOpt = DEFAULT_CONFIG,
    out_dir: Annotated[Path, typer.Option("--out-dir")] = Path("reports/results"),
    labels: Annotated[str, typer.Option(help="silver | gold (adjudicated issues only)")] = "silver",
    with_blind_pass: Annotated[
        bool, typer.Option(help="Add the annotators' blind pass (only if independent of the gold).")
    ] = False,
) -> None:
    """Write the results table (latest run per experiment) to reports/results/<split>.md."""
    from triagelab.data.splits import parse_split
    from triagelab.eval.report import load_scored_runs, rescore_on_gold, results_table

    if labels not in ("silver", "gold"):
        raise typer.BadParameter("labels must be silver or gold")
    cfg = load_config(config)
    runs = load_scored_runs(cfg.paths.runs_dir)
    if labels == "gold":
        runs = rescore_on_gold(
            runs, cfg.paths.runs_dir, cfg, parse_split(split), include_blind_pass=with_blind_pass
        )
    table = results_table(runs, split)
    if labels == "gold":
        table = table.replace("Silver labels,", "Gold labels (adjudicated issues only),", 1)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / (f"{split}.md" if labels == "silver" else f"{split}-gold.md")
    heading = f"# Results: {split} split ({labels} labels)"
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


@app.command()
def label(
    profile: ProfileOpt = Path("configs/repos/python__cpython.yaml"),
    data_dir: DataDirOpt = Path("data"),
    annotator: Annotated[str, typer.Option(help="Recorded with every label.")] = "owner",
    port: Annotated[int, typer.Option(help="Local port for the app.")] = 8501,
) -> None:
    """Open the labeling app in the browser (gold labels, blind first; see M5)."""
    import subprocess
    import sys

    from triagelab import labeling

    app_path = Path(labeling.__file__).parent / "app.py"
    env = {
        **os.environ,
        "TRIAGELAB_PROFILE": str(profile.resolve()),
        "TRIAGELAB_DATA_DIR": str(data_dir.resolve()),
        "TRIAGELAB_ANNOTATOR": annotator,
    }
    command = [
        sys.executable, "-m", "streamlit", "run", str(app_path),
        "--server.port", str(port),
        "--browser.gatherUsageStats", "false",  # Streamlit sends usage stats unless told not to
    ]  # fmt: skip
    raise typer.Exit(subprocess.run(command, env=env, check=False).returncode)


@judge_app.command("sample")
def judge_sample(
    runs: Annotated[
        list[str], typer.Argument(help="NAME=RUN_DIR pairs whose triage comments are rated.")
    ],
    data_dir: DataDirOpt = Path("data"),
    seed: int = 0,
) -> None:
    """Freeze the set of comments to rate (one per dev issue, system chosen at random)."""
    from triagelab.labeling.ratings import RatingStore, sample_items

    pairs = dict(r.split("=", 1) for r in runs)
    items = sample_items({name: Path(path) for name, path in pairs.items()}, seed=seed)
    store = RatingStore(data_dir)
    store.write_items(items)
    typer.echo(f"{len(items)} comments to rate written to {store.items_file.as_posix()}")


@judge_app.command("calibrate")
def judge_calibrate(
    split: Annotated[
        str, typer.Option(help="judge-dev (iterate), judge-test (once)")
    ] = "judge-dev",
    config: ConfigOpt = Path("configs/judge/judge.yaml"),
    rubric_path: Annotated[Path, typer.Option("--rubric")] = Path("configs/judge/rubric.yaml"),
    bias: Annotated[bool, typer.Option(help="Also run the verbosity/order checks.")] = True,
    out_dir: Annotated[Path, typer.Option("--out-dir")] = Path("reports/judge"),
) -> None:
    """Judge the human-rated comments and report agreement (QWK, exact, adjacent)."""
    from triagelab.data.profile import load_profile
    from triagelab.eval.judge import (
        Judge,
        JudgeTestGuard,
        agreement,
        bias_shift,
        items_in,
        render_agreement,
        save_scores,
    )
    from triagelab.labeling.gold import load_items
    from triagelab.labeling.ratings import RatingStore, load_rubric

    if split not in ("judge-dev", "judge-test"):
        raise typer.BadParameter("split must be judge-dev or judge-test")
    load_dotenv()
    cfg = load_config(config)
    rubric = load_rubric(rubric_path)
    profile = load_profile(cfg.dataset.profile)
    store = RatingStore(cfg.dataset.data_dir)
    guard = JudgeTestGuard(cfg.dataset.data_dir / "gold" / "judge_test_log.jsonl")
    if split == "judge-test":
        guard.authorize(rubric.version)
    ratings = store.ratings()
    rated = [i for i in items_in(split, store.items()) if i.item_id in ratings]
    if not rated:
        typer.echo(f"No human ratings in {split} yet: rate comments in `triagelab label` first.")
        raise typer.Exit(1)
    issues = {i.snapshot.issue_ref: i for i in load_items(cfg.dataset.data_dir, profile)}
    pairs = [(i, issues[i.issue_ref]) for i in rated]
    run_dir, _ = create_run(
        cfg, runs_dir=cfg.paths.runs_dir, command=f"judge calibrate --split {split}",
        now=datetime.now(UTC), git=git_info(Path.cwd()), details={"split": split},
    )  # fmt: skip
    client = wiring.build_llm_client(cfg, run_id=run_dir.name)
    judge = Judge(client, cfg.llm, rubric, profile.repo)
    plain = judge.score_all(pairs, workers=cfg.eval.concurrency, log=typer.echo)
    save_scores(run_dir / "judge_scores.jsonl", plain)
    table = render_agreement(agreement(ratings, plain, rubric), split)
    lines = [f"# Judge agreement: {split}", "", table]
    if bias and split == "judge-dev":
        for variant in ("padded", "reversed"):
            other = judge.score_all(
                pairs, variant=variant, workers=cfg.eval.concurrency, log=typer.echo
            )
            save_scores(run_dir / f"judge_scores_{variant}.jsonl", other)
            shift = ", ".join(f"{k} {v:+.2f}" for k, v in bias_shift(plain, other).items())
            lines += ["", f"- **{variant}** mean score shift: {shift}"]
    write_cost(run_dir, client.stats)
    text = "\n".join(lines) + "\n"
    typer.echo(text)
    typer.echo(f"cost ${client.stats.cost_usd:.4f}")
    if split == "judge-test":
        guard.record(rubric.version)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{split}.md").write_bytes(text.encode("utf-8"))


@app.command("gold-report")
def gold_report(
    split: str = "dev",
    config: ConfigOpt = DEFAULT_CONFIG,
    out_dir: Annotated[Path, typer.Option("--out-dir")] = Path("reports/gold"),
) -> None:
    """Label noise (silver vs gold kappa), what the evidence changed, and labeling time."""
    from statistics import median

    from triagelab.data.profile import load_profile
    from triagelab.data.splits import parse_split
    from triagelab.eval.dataset import load_split
    from triagelab.eval.gold_labels import agreement_by_task, gold_from, render_agreement, usable
    from triagelab.labeling.gold import GoldStore, gold_path, label_vocabulary

    cfg = load_config(config)
    profile = load_profile(cfg.dataset.profile)
    data_dir = cfg.dataset.data_dir
    records = usable(GoldStore(gold_path(data_dir, profile)).load())
    silver = {
        e.snapshot.issue_ref: e.gold for e in load_split(data_dir, profile, parse_split(split))
    }
    done = [r for ref, r in records.items() if ref in silver and r.final is not None]
    if not done:
        typer.echo(f"No adjudicated {split} issues yet: label them with `triagelab label`.")
        raise typer.Exit(1)
    vocab = [label for group in label_vocabulary(data_dir, profile).values() for label in group]
    finals = [gold_from(r.final, profile) for r in done if r.final is not None]
    blinds = [gold_from(r.blind, profile) for r in done]
    sections = [
        f"# Gold labels: {split} ({len(done)} issues adjudicated)",
        "## Label noise: silver vs gold",
        render_agreement(
            agreement_by_task(
                [(silver[r.issue_ref], g) for r, g in zip(done, finals, strict=True)], vocab
            ),
            "task",
        ),
        "## What the evidence changed: blind vs final (same person)",
        render_agreement(agreement_by_task(list(zip(blinds, finals, strict=True)), vocab), "task"),
    ]
    seconds = [r.blind_seconds for r in done if r.blind_seconds > 0]
    if seconds:  # a model annotator records no labeling time
        sections.append(f"Median blind-pass time: {median(seconds):.0f} s per issue.")
    text = "\n\n".join(sections) + "\n"
    typer.echo(text)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{split}.md").write_bytes(text.encode("utf-8"))


@failures_app.command("tag")
def failures_tag(
    run_dir: Annotated[Path, typer.Argument(help="An agent run folder.")],
    labels: Annotated[str, typer.Option(help="silver | gold")] = "silver",
    config: ConfigOpt = Path("configs/judge/judge.yaml"),
    taxonomy_path: Annotated[Path, typer.Option("--taxonomy")] = Path(
        "configs/failures/taxonomy.yaml"
    ),
) -> None:
    """Tag every failure of a run with the LLM tagger; writes <run>/failures.parquet."""
    from concurrent.futures import ThreadPoolExecutor

    from triagelab.eval.failure_tagger import (
        FailureTagger,
        TaggedFailure,
        load_taxonomy,
        write_failures,
    )
    from triagelab.eval.failures import Failure, find_failures
    from triagelab.eval.report import examples_for, load_run
    from triagelab.harness.trace_stats import load_events

    if labels not in ("silver", "gold"):
        raise typer.BadParameter("labels must be silver or gold")
    load_dotenv()
    cfg = load_config(config)
    taxonomy = load_taxonomy(taxonomy_path)
    run_cfg, split, _ = load_run(run_dir)
    predictions, events = load_events(run_dir)
    examples = examples_for(run_cfg, split, labels)
    titles = {e.snapshot.issue_ref: e.snapshot.title for e in examples}
    failures = find_failures(examples, predictions)
    client = wiring.build_llm_client(cfg, run_id=f"{run_dir.name}-failures")
    tagger = FailureTagger(client, cfg.llm, taxonomy)

    def one(failure: Failure) -> TaggedFailure:
        return tagger.tag(failure, events.get(failure.trace_id, []), titles[failure.issue_ref])

    with ThreadPoolExecutor(max_workers=cfg.eval.concurrency) as pool:
        tagged = list(pool.map(one, failures))
    write_failures(run_dir, tagged, taxonomy.version)
    typer.echo(f"{len(tagged)} failures tagged; cost ${client.stats.cost_usd:.4f}")


@failures_app.command("validate")
def failures_validate(
    run_dir: Annotated[Path, typer.Argument(help="A run tagged by both the person and the LLM.")],
    config: ConfigOpt = DEFAULT_CONFIG,
    taxonomy_path: Annotated[Path, typer.Option("--taxonomy")] = Path(
        "configs/failures/taxonomy.yaml"
    ),
    out_dir: Annotated[Path, typer.Option("--out-dir")] = Path("reports/failures"),
) -> None:
    """Agreement between the reference failure tags and the LLM tagger's, per category."""
    from triagelab.data.storage import read_parquet
    from triagelab.eval.failure_tagger import (
        FAILURES_FILE,
        human_categories,
        load_taxonomy,
        tag_agreement,
    )
    from triagelab.labeling.failure_tags import FailureTagStore

    cfg = load_config(config)
    taxonomy = load_taxonomy(taxonomy_path)
    tags = FailureTagStore(cfg.dataset.data_dir).load()
    human = {
        ref: human_categories(tag, taxonomy)
        for (run_id, ref), tag in tags.items()
        if run_id == run_dir.name
    }
    llm = {r["issue_ref"]: set(r["categories"]) for r in read_parquet(run_dir / FAILURES_FILE)}
    rows, exact, jaccard = tag_agreement(human, llm, taxonomy.names())
    annotators = ", ".join(
        sorted({t.annotator for (run, _), t in tags.items() if run == run_dir.name})
    )
    lines = [
        f"# Failure tagger validation: {run_dir.name}",
        "",
        f"Taxonomy v{taxonomy.version}; reference tags by {annotators}; "
        f"{rows[0].n if rows else 0} failures tagged by both. Exact category-set agreement "
        f"{exact:.2f}, mean Jaccard {jaccard:.2f}. A category counts as validated at kappa >= 0.6.",
        "",
        "| category | reference | tagger | kappa | validated |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        kappa = "n/a" if r.kappa is None else f"{r.kappa:.2f}"
        ok = "yes" if r.kappa is not None and r.kappa >= 0.6 else "no"
        lines.append(f"| {r.category} | {r.human} | {r.llm} | {kappa} | {ok} |")
    text = "\n".join(lines) + "\n"
    typer.echo(text)
    out = out_dir / f"{run_dir.name}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(text.encode("utf-8"))


AnnotatorOpt = Annotated[str, typer.Option(help="Recorded with every answer: a person or a model.")]


def _labels(labels: str) -> Literal["silver", "gold"]:
    if labels not in ("silver", "gold"):
        raise typer.BadParameter("labels must be silver or gold")
    return "gold" if labels == "gold" else "silver"


@annotate_app.command("export-gold")
def annotate_export_gold(
    out_dir: Annotated[Path, typer.Option("--out")],
    pass_: Annotated[str, typer.Option("--pass", help="blind | final")] = "blind",
    split: str = "dev",
    batch_size: int = 20,
    config: ConfigOpt = DEFAULT_CONFIG,
) -> None:
    """Write gold-label batches; final-pass evidence only for blind-labeled issues."""
    from triagelab.data.profile import load_profile
    from triagelab.labeling.batches import export_gold_blind, export_gold_final, gold_context

    cfg = load_config(config)
    ctx = gold_context(cfg.dataset.data_dir, load_profile(cfg.dataset.profile))
    chosen = [i for i in ctx.items if i.split == split]
    if pass_ == "blind":
        files = export_gold_blind(
            chosen, ctx.store.load(), ctx.vocab, ctx.components, out_dir, batch_size
        )
    elif pass_ == "final":
        files = export_gold_final(chosen, ctx.store.load(), out_dir, batch_size)
    else:
        raise typer.BadParameter("--pass must be blind or final")
    typer.echo(f"{len(files)} batch file(s) in {out_dir.as_posix()}")


@annotate_app.command("import-gold")
def annotate_import_gold(
    files: Annotated[list[Path], typer.Argument(help="JSONL answer files.")],
    annotator: AnnotatorOpt,
    pass_: Annotated[str, typer.Option("--pass", help="blind | final")] = "blind",
    config: ConfigOpt = DEFAULT_CONFIG,
) -> None:
    """Validate and store gold-label answers (a bad file stores nothing)."""
    from triagelab.data.profile import load_profile
    from triagelab.labeling.batches import gold_context, import_gold_blind, import_gold_final

    cfg = load_config(config)
    ctx = gold_context(cfg.dataset.data_dir, load_profile(cfg.dataset.profile))
    by_ref = {i.snapshot.issue_ref: i for i in ctx.items}
    for path in files:
        if pass_ == "blind":
            n = import_gold_blind(path, ctx.store, by_ref, ctx.vocab, ctx.components, annotator)
        else:
            n = import_gold_final(path, ctx.store, ctx.vocab, ctx.components)
        typer.echo(f"{path.name}: {n} {pass_} answers stored")


@annotate_app.command("export-ratings")
def annotate_export_ratings(
    out_dir: Annotated[Path, typer.Option("--out")],
    rubric_path: Annotated[Path, typer.Option("--rubric")] = Path("configs/judge/rubric.yaml"),
    batch_size: int = 25,
    config: ConfigOpt = DEFAULT_CONFIG,
) -> None:
    """Write comment-rating batches (opaque ids; keys go to <out>-keys/)."""
    from triagelab.data.profile import load_profile
    from triagelab.labeling.batches import export_ratings, gold_context
    from triagelab.labeling.ratings import RatingStore, load_rubric

    cfg = load_config(config)
    ctx = gold_context(cfg.dataset.data_dir, load_profile(cfg.dataset.profile))
    store = RatingStore(cfg.dataset.data_dir)
    issues = {i.snapshot.issue_ref: i for i in ctx.items}
    files = export_ratings(
        store.items(), issues, load_rubric(rubric_path), set(store.ratings()), out_dir, batch_size
    )
    typer.echo(f"{len(files)} batch file(s) in {out_dir.as_posix()}")


@annotate_app.command("import-ratings")
def annotate_import_ratings(
    file: Path,
    key: Annotated[Path, typer.Option(help="The batch's .key.json file.")],
    annotator: AnnotatorOpt,
    rubric_path: Annotated[Path, typer.Option("--rubric")] = Path("configs/judge/rubric.yaml"),
    config: ConfigOpt = DEFAULT_CONFIG,
) -> None:
    """Validate and store comment ratings."""
    from triagelab.labeling.batches import import_ratings
    from triagelab.labeling.ratings import RatingStore, load_rubric

    cfg = load_config(config)
    store = RatingStore(cfg.dataset.data_dir)
    n = import_ratings(file, key, store, load_rubric(rubric_path), annotator)
    typer.echo(f"{file.name}: {n} ratings stored")


@annotate_app.command("export-failures")
def annotate_export_failures(
    run_dir: Path,
    out_dir: Annotated[Path, typer.Option("--out")],
    labels: str = "gold",
    limit: int = 50,
    config: ConfigOpt = DEFAULT_CONFIG,
) -> None:
    """Write failure-review batches: the diff, the issue and the agent's steps."""
    from triagelab.data.profile import load_profile
    from triagelab.labeling.batches import export_failures, gold_context, run_failures
    from triagelab.labeling.failure_tags import FailureTagStore

    cfg = load_config(config)
    ctx = gold_context(cfg.dataset.data_dir, load_profile(cfg.dataset.profile))
    failures, events = run_failures(run_dir, _labels(labels))
    tags = FailureTagStore(cfg.dataset.data_dir).load()
    tagged = {ref for (run, ref) in tags if run == run_dir.name}
    issues = {i.snapshot.issue_ref: i for i in ctx.items}
    files = export_failures(run_dir.name, failures, events, issues, tagged, out_dir, limit)
    typer.echo(f"{len(failures)} failures; {len(files)} batch file(s) in {out_dir.as_posix()}")


@annotate_app.command("import-failures")
def annotate_import_failures(
    run_dir: Path,
    file: Path,
    annotator: AnnotatorOpt,
    labels: str = "gold",
    config: ConfigOpt = DEFAULT_CONFIG,
) -> None:
    """Validate and store failure tags for a run."""
    from triagelab.labeling.batches import import_failure_tags, run_failures
    from triagelab.labeling.failure_tags import FailureTagStore

    cfg = load_config(config)
    failures, _ = run_failures(run_dir, _labels(labels))
    store = FailureTagStore(cfg.dataset.data_dir)
    n = import_failure_tags(
        file, run_dir.name, {f.issue_ref: f for f in failures}, store, annotator
    )
    typer.echo(f"{file.name}: {n} tags stored")


@skills_app.command("bootstrap")
def skills_bootstrap(
    name: Annotated[str, typer.Option(help="Skill folder name, e.g. triage-cpython-auto.")],
    config: ConfigOpt = Path("configs/judge/judge.yaml"),
    skills_dir: Annotated[Path, typer.Option("--skills-dir")] = Path("skills"),
    force: Annotated[bool, typer.Option(help="Overwrite an existing skill folder.")] = False,
) -> None:
    """Generate a repository skill from CONTRIBUTING, label descriptions and the train split."""
    from triagelab.data.checkout import checkout_dir
    from triagelab.data.profile import load_profile
    from triagelab.eval.dataset import family_vocabulary, load_split
    from triagelab.skills.bootstrap import (
        collect_sources,
        fetch_label_descriptions,
        generate,
        write_skill,
    )
    from triagelab.skills.loader import parse_skill

    load_dotenv()
    cfg = load_config(config)
    profile = load_profile(cfg.dataset.profile)
    directory = skills_dir / name
    if directory.exists() and not force:
        raise typer.BadParameter(
            f"{directory} exists; a generated skill is not regenerated silently"
        )
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        typer.echo("GITHUB_TOKEN is not set (needed once to read label descriptions).", err=True)
        raise typer.Exit(1)
    data_dir = cfg.dataset.data_dir
    labels = fetch_label_descriptions(
        profile.repo, token, data_dir / "raw" / profile.slug / "labels.json"
    )
    github_dir = checkout_dir(data_dir, profile) / ".github"
    contributing = next(
        (f.read_text(encoding="utf-8") for f in sorted(github_dir.glob("CONTRIBUTING*"))), ""
    )
    train = load_split(data_dir, profile, "train")
    sources = collect_sources(profile, train, family_vocabulary(train, 10), labels, contributing)
    client = wiring.build_llm_client(cfg, run_id=f"skills-bootstrap-{name}")
    skill = generate(client, cfg.llm, profile.repo, sources)
    write_skill(skill, directory, sources_note="CONTRIBUTING, label descriptions, train split")
    problems = parse_skill(directory).problems
    typer.echo(f"wrote {directory.as_posix()} (cost ${client.stats.cost_usd:.4f})")
    if problems:
        typer.echo(f"spec problems: {problems}", err=True)
        raise typer.Exit(1)


GateBaselineOpt = Annotated[
    Path, typer.Option("--baseline", help="The blessed baseline (a run folder).")
]
DEFAULT_GATE_BASELINE = Path("reports/gate/baseline")


@gate_app.command("check")
def gate_check(
    candidate: Annotated[Path, typer.Argument(help="The candidate run folder.")],
    baseline: GateBaselineOpt = DEFAULT_GATE_BASELINE,
    gate_config: Annotated[Path, typer.Option("--gate")] = Path("configs/gate/gate.yaml"),
    out: Annotated[Path | None, typer.Option("--out", help="Also write the report here.")] = None,
) -> None:
    """Compare a candidate run with the baseline; exit 1 if the gate fails."""
    from triagelab.eval.gate import check, load_gate_config, render

    report = check(baseline, candidate, load_gate_config(gate_config))
    text = render(report)
    typer.echo(text)
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(text.encode("utf-8"))
    if report.verdict == "fail":
        raise typer.Exit(code=1)


@gate_app.command("bless")
def gate_bless(
    run_dir: Annotated[Path, typer.Argument(help="The run to make the baseline.")],
    dest: GateBaselineOpt = DEFAULT_GATE_BASELINE,
    subset: Annotated[Path, typer.Option("--subset")] = Path("configs/gate/dev-subset.txt"),
) -> None:
    """Make a run the gate's baseline, restricted to the gate's subset (commit the result)."""
    from triagelab.config import read_subset
    from triagelab.eval.gate import bless

    n = bless(run_dir, dest, read_subset(subset))
    typer.echo(f"baseline: {run_dir.name} ({n} issues) -> {dest.as_posix()}")


@gate_app.command("subset")
def gate_subset(
    n: Annotated[int, typer.Option(help="Subset size.")] = 50,
    out: Annotated[Path, typer.Option("--out")] = Path("configs/gate/dev-subset.txt"),
    config: ConfigOpt = DEFAULT_CONFIG,
) -> None:
    """Pick the gate's fixed subset from the adjudicated, usable dev issues."""
    from triagelab.data.profile import load_profile
    from triagelab.eval.gate import pick_subset
    from triagelab.labeling.gold import GoldStore, gold_path

    cfg = load_config(config)
    profile = load_profile(cfg.dataset.profile)
    records = GoldStore(gold_path(cfg.dataset.data_dir, profile)).load().values()
    refs = [r.issue_ref for r in records if r.split == "dev" and not r.unusable]
    chosen = pick_subset(refs, n)
    header = (
        f"# The regression gate's fixed dev subset: {len(chosen)} of {len(refs)} adjudicated,\n"
        "# usable dev issues, chosen by `triagelab gate subset` (smallest stable hash).\n"
    )
    out.write_bytes((header + "\n".join(chosen) + "\n").encode("utf-8"))
    typer.echo(f"{len(chosen)} issues -> {out.as_posix()}")


@gate_app.command("pack")
def gate_pack(
    profile_path: ProfileOpt,
    data_dir: DataDirOpt = Path("data"),
    out: Annotated[Path, typer.Option("--out")] = Path("dist/evalpack.tar.gz"),
) -> None:
    """Pack the dataset tables (no test rows) and the retrieval index for CI."""
    from triagelab.data.evalpack import build_pack
    from triagelab.data.profile import load_profile

    out.parent.mkdir(parents=True, exist_ok=True)
    manifest = build_pack(data_dir, load_profile(profile_path), out)
    size = out.stat().st_size / 1e6
    typer.echo(f"{len(manifest.files)} files, splits {manifest.splits}, {size:.1f} MB -> {out}")


@gate_app.command("unpack")
def gate_unpack(
    archive: Annotated[Path, typer.Argument(help="An eval pack (.tar.gz).")],
    profile_path: ProfileOpt,
    data_dir: DataDirOpt = Path("data"),
) -> None:
    """Unpack and verify an eval pack; refuses anything from the test period."""
    from triagelab.data.evalpack import PackError, extract_pack
    from triagelab.data.profile import load_profile

    try:
        manifest = extract_pack(archive, data_dir, load_profile(profile_path))
    except PackError as err:
        typer.echo(f"eval pack rejected: {err}", err=True)
        raise typer.Exit(code=1) from err
    typer.echo(
        f"{len(manifest.files)} files verified, splits {manifest.splits}, "
        f"history before {manifest.history_cutoff}"
    )


@app.command()
def deltas(
    spec_path: Annotated[
        Path, typer.Argument(help="A comparison spec, e.g. reports/experiments/m6.yaml.")
    ],
    labels: Annotated[str, typer.Option(help="silver | gold (adjudicated issues only)")] = "gold",
    config: ConfigOpt = DEFAULT_CONFIG,
) -> None:
    """Paired-bootstrap deltas for a declared set of comparisons; writes <spec>-<labels>.md."""
    from triagelab.eval.report import DeltaSpec, deltas_table, failure_table

    if labels not in ("silver", "gold"):
        raise typer.BadParameter("labels must be silver or gold")
    spec = DeltaSpec.model_validate(yaml.safe_load(spec_path.read_text(encoding="utf-8")))
    cfg = load_config(config)
    table = deltas_table(spec, cfg.paths.runs_dir, _labels(labels))
    failures = failure_table(spec, cfg.paths.runs_dir) if labels == "gold" else None
    if failures:
        table += f"\n## Failure categories\n\n{failures}"
    out = spec_path.with_name(f"{spec_path.stem}-{labels}.md")
    out.write_bytes(f"# {spec.title} ({labels} labels)\n\n{table}".encode())
    typer.echo(table)
    typer.echo(f"written to {out.as_posix()}")


@app.command()
def calibration(
    spec_path: Annotated[Path, typer.Argument(help="A calibration spec (title, sources).")],
    labels: Annotated[str, typer.Option(help="silver | gold (adjudicated issues only)")] = "gold",
    figures_dir: Annotated[Path, typer.Option("--figures-dir")] = Path("reports/figures"),
) -> None:
    """Calibration of each source's confidences: tables, slices, reliability and
    risk-coverage figures. Writes <spec>-<labels>.md next to the spec."""
    from triagelab.eval.calibration_report import CalibrationSpec, build_report

    spec = CalibrationSpec.model_validate(yaml.safe_load(spec_path.read_text(encoding="utf-8")))
    cfg = load_config(DEFAULT_CONFIG)
    text = build_report(spec, cfg.paths.runs_dir, _labels(labels), figures_dir, spec_path.stem)
    out = spec_path.with_name(f"{spec_path.stem}-{labels}.md")
    out.write_bytes(text.encode())
    typer.echo(text)
    typer.echo(f"written to {out.as_posix()}")
