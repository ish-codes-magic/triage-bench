"""Run a triage system over a dataset split and score it (AGENTS.md §12.1).

`triagelab eval --config configs/experiments/<x>.yaml --split dev`

- Parallel: issues are triaged on a thread pool (model calls are I/O-bound).
- Resumable: predictions are appended to predictions.jsonl as they complete; `--resume`
  continues a run, skipping issues already predicted.
- Budget-guarded: a BudgetExceededError stops new work, keeps what finished, and leaves
  the run unscored.
- Test-set hygiene: the test split needs an explicit flag and may be evaluated at most
  twice over the project's lifetime; every test run is logged (AGENTS.md §7.4).
"""

import json
import threading
import time
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from triagelab import wiring
from triagelab.baselines.classifier import ClassifierTriager
from triagelab.baselines.llm_single_shot import LLMSingleShotTriager
from triagelab.baselines.majority import MajorityTriager
from triagelab.config import CascadeConfig, Config, RoutedConfig, read_subset
from triagelab.cost import BudgetExceededError
from triagelab.data.build import dataset_paths
from triagelab.data.profile import RepoProfile, load_profile
from triagelab.data.splits import Split
from triagelab.data.storage import append_jsonl, read_jsonl, write_json, write_parquet
from triagelab.eval.dataset import EvalExample, family_vocabulary, load_history, load_split
from triagelab.eval.registry import RunManifest, create_run, git_info, write_cost
from triagelab.eval.score import Scorecard, score
from triagelab.eval.test_session import TestSetLockedError, authorize, record
from triagelab.llm_client import CallStats, CassetteMissError, LLMClient
from triagelab.triage import Triager, TriageResult

INFRA_ERROR_PREFIX = "infra: "
Log = Callable[[str], None]


class RunOutcome(BaseModel):
    run_id: str
    run_dir: Path
    completed: int
    total: int
    stopped_reason: str | None
    scorecard: Scorecard | None
    spent_usd: float = 0.0  # money actually spent by this run (cache hits are free)


def build_triager(
    cfg: Config,
    profile: RepoProfile,
    client: Callable[[Config], LLMClient],
    *,
    run_id: str,
    run_dir: Path,
    stack: ExitStack,
) -> Triager:
    if cfg.system is None:
        raise ValueError(f"Config {cfg.name!r} has no `system:` section; use an experiment config.")
    data_dir = cfg.dataset.data_dir
    train = load_split(data_dir, profile, "train")
    kind = cfg.system.kind
    if kind == "majority":
        return MajorityTriager(train)
    if kind == "classifier":
        return ClassifierTriager(
            train, load_history(data_dir, profile), min_label_count=cfg.system.min_label_count
        )
    if cfg.system.decisions is not None:  # kind == "decisions"
        from triagelab.decisions.factory import build_decision_triager

        return build_decision_triager(
            cfg, cfg.system.decisions, profile, train, lambda: client(cfg)
        )
    if cfg.system.routed is not None:  # kind == "routed"
        return _build_routed(
            cfg, cfg.system.routed, profile, client, run_id=run_id, run_dir=run_dir, stack=stack
        )
    if cfg.system.cascade is not None:  # kind == "cascade"
        return _build_cascade(
            cfg, cfg.system.cascade, profile, client, run_id=run_id, run_dir=run_dir, stack=stack
        )
    if cfg.system.agent is not None:  # kind == "agent" (the config validator pairs them)
        from triagelab.harness.factory import build_agent  # MCP/OTel imports only when needed

        return build_agent(
            cfg,
            cfg.system.agent,
            profile,
            family_vocabulary(train, cfg.system.min_label_count),
            client(cfg),
            max_body_chars=cfg.system.max_body_chars,
            family_label_min_confidence=cfg.system.family_label_min_confidence,
            run_id=run_id,
            run_dir=run_dir,
            stack=stack,
        )
    return LLMSingleShotTriager(
        client(cfg),
        cfg.llm,
        profile,
        family_vocabulary(train, cfg.system.min_label_count),
        max_body_chars=cfg.system.max_body_chars,
        family_label_min_confidence=cfg.system.family_label_min_confidence,
    )


def _part(cfg: Config, path: Path) -> Config:
    """A composed system's part: its own model and system, in the composing run's
    environment (where the data, cache, budget and traces live is the run's decision)."""
    from triagelab.config import load_config

    return load_config(path).model_copy(
        update={
            "dataset": cfg.dataset,
            "paths": cfg.paths,
            "cache": cfg.cache,
            "budget": cfg.budget,
            "tracing": cfg.tracing,
        }
    )


def _build_cascade(
    cfg: Config,
    cascade: CascadeConfig,
    profile: RepoProfile,
    client: Callable[[Config], LLMClient],
    *,
    run_id: str,
    run_dir: Path,
    stack: ExitStack,
) -> Triager:
    from triagelab.decisions.live_cascade import CascadeTriager, routing_log

    def tier(name: str, path: Path) -> Triager:
        # Each tier keeps its own traces and server log, so either can be read alone.
        tier_dir = run_dir / name
        tier_dir.mkdir(exist_ok=True)
        return build_triager(
            _part(cfg, path), profile, client, run_id=run_id, run_dir=tier_dir, stack=stack
        )

    return CascadeTriager(
        tier("cheap", cascade.cheap),
        tier("full", cascade.full),
        profile.taxonomy.type,
        cascade.tau,
        on_routing=routing_log(run_dir),
    )


def _build_routed(
    cfg: Config,
    routed: RoutedConfig,
    profile: RepoProfile,
    client: Callable[[Config], LLMClient],
    *,
    run_id: str,
    run_dir: Path,
    stack: ExitStack,
) -> Triager:
    """Build every part from its own experiment config, in this run's environment."""
    from triagelab.decisions.questions import QuestionId
    from triagelab.decisions.routed import RoutedTriager

    def part(path: Path) -> Config:
        return _part(cfg, path)

    def build(sub: Config) -> Triager:
        return build_triager(sub, profile, client, run_id=run_id, run_dir=run_dir, stack=stack)

    deciders: dict[QuestionId, Triager] = {}
    questions: tuple[tuple[QuestionId, Path | None], ...] = (
        ("type", routed.type),
        ("component", routed.component),
    )
    for qid, path in questions:
        if path is None:
            continue
        sub = part(path)
        if sub.system is None or sub.system.decisions is None:
            raise ValueError(f"routed.{qid} must be a decisions config: {path}")
        only = sub.system.decisions.model_copy(update={"questions": [qid]})
        system = sub.system.model_copy(update={"decisions": only})
        deciders[qid] = build(sub.model_copy(update={"system": system}))
    return RoutedTriager(build(part(routed.base)), deciders, profile.taxonomy.type)


def _subset(examples: list[EvalExample], refs: list[str], split: Split) -> list[EvalExample]:
    """The listed issues, in the split's order. Every ref must be in the split, so a
    subset can never pull an issue from another split (e.g. test) into a run."""
    by_ref = {e.snapshot.issue_ref: e for e in examples}
    outside = [r for r in refs if r not in by_ref]
    if outside:
        raise ValueError(
            f"{len(outside)} subset issues are not in the {split} split: {outside[:3]}"
        )
    wanted = set(refs)
    return [e for e in examples if e.snapshot.issue_ref in wanted]


def _dataset_hash(cfg: Config, profile: RepoProfile) -> str:
    report = dataset_paths(cfg.dataset.data_dir, cfg.dataset.reports_dir, profile).report_json
    if not report.exists():
        return "unknown"
    return str(json.loads(report.read_text(encoding="utf-8")).get("dataset_hash", "unknown"))


def _timed(triager: Triager, example: EvalExample, run_id: str) -> TriageResult:
    started = time.perf_counter()
    try:
        result = triager.triage(example.snapshot)
    except (BudgetExceededError, CassetteMissError):
        raise  # stop the run: retrying can't help, and CI must fail loudly
    except Exception as err:  # one bad issue must not sink the run
        # Anything *raised* by a system is infrastructure (network, rate limit), not a model
        # answer. Marked so a resume or the retry pass can re-run it instead of scoring it.
        result = TriageResult(
            issue_ref=example.snapshot.issue_ref,
            error=f"{INFRA_ERROR_PREFIX}{type(err).__name__}: {err}",
        )
    elapsed = round((time.perf_counter() - started) * 1000)
    return result.model_copy(update={"run_id": run_id, "latency_ms": result.latency_ms or elapsed})


def _needs_run(result: TriageResult | None) -> bool:
    return result is None or (result.error or "").startswith(INFRA_ERROR_PREFIX)


def run_eval(
    cfg: Config,
    *,
    split: Split,
    runs_dir: Path,
    command: str,
    log: Log,
    limit: int | None = None,
    session: Path | None = None,
    sessions_root: Path = Path(),
    resume_dir: Path | None = None,
    sample: int = 0,
) -> RunOutcome:
    """`session`: the frozen test session this run belongs to; required for the test split
    (eval/test_session.py). `sessions_root` is where session files live (the repository).

    `sample` > 0 repeats an evaluation with fresh model calls, for the consistency study
    (§12.3). A resumed run keeps the sample index it was started with.
    """
    profile = load_profile(cfg.dataset.profile)
    frozen = None
    if resume_dir is not None:
        started = RunManifest.model_validate_json(
            (resume_dir / "manifest.json").read_text(encoding="utf-8")
        )
        sample = int(started.details.get("sample", "0"))
    if split == "test" and sample:
        raise TestSetLockedError("A repeat run would be another look at the test split.")
    if split == "test":
        if session is None:
            raise TestSetLockedError(
                "The test split is locked. Iterate on dev; the test split is evaluated only "
                "through a frozen session (`triagelab test-session freeze`, AGENTS.md §7.4)."
            )
        if limit is not None or cfg.eval.subset is not None:
            raise TestSetLockedError("A test session evaluates the whole test split, not a part.")
        frozen = authorize(
            session,
            cfg,
            profile.slug,
            dataset_hash=_dataset_hash(cfg, profile),
            root=sessions_root,
        )
    examples = load_split(cfg.dataset.data_dir, profile, split)
    if cfg.eval.subset is not None:
        examples = _subset(examples, read_subset(cfg.eval.subset), split)
    examples = examples[:limit]
    if resume_dir is not None:
        run_dir, run_id = resume_dir, resume_dir.name
    else:
        assert cfg.system is not None
        run_dir, manifest = create_run(
            cfg,
            runs_dir=runs_dir,
            command=command,
            now=datetime.now(UTC),
            git=git_info(Path.cwd()),
            details={
                "split": split,
                "system": cfg.system.kind,
                "model": cfg.llm.model if cfg.system.kind in ("llm_single_shot", "agent") else "-",
                "skills": ",".join(cfg.system.agent.skills) if cfg.system.agent else "-",
                "dataset_hash": _dataset_hash(cfg, profile),
                "issues": str(len(examples)),
                "subset": cfg.eval.subset.as_posix() if cfg.eval.subset else "-",
                # Only recorded for repeats, so first runs keep the manifest they always had.
                **({"sample": str(sample)} if sample else {}),
            },
        )
        run_id = manifest.run_id

    clients: list[LLMClient] = []

    def client(for_cfg: Config) -> LLMClient:
        # One client per (sub-)config: a routed system's parts use different routes.
        clients.append(wiring.build_llm_client(for_cfg, run_id=run_id, sample=sample))
        return clients[-1]

    if frozen is not None and session is not None:
        record(session, frozen, cfg, run_id, "started")
    kind = cfg.system.kind if cfg.system else "?"
    log(f"run {run_id}: building {kind} on {split} ({len(examples)} issues)")
    with ExitStack() as stack:  # agent resources: the MCP server process, trace export
        triager = build_triager(cfg, profile, client, run_id=run_id, run_dir=run_dir, stack=stack)

        predictions_path = run_dir / "predictions.jsonl"
        # Later lines win, so a re-run issue replaces its earlier (failed) attempt.
        done = {p.issue_ref: p for p in read_jsonl(predictions_path, TriageResult)}
        todo = [e for e in examples if _needs_run(done.get(e.snapshot.issue_ref))]
        stopped: str | None = None
        write_lock = threading.Lock()

        def triage_all(batch: list[EvalExample], workers: int) -> str | None:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                pending: set[Future[TriageResult]] = {
                    pool.submit(_timed, triager, e, run_id) for e in batch
                }
                finished = 0
                while pending:
                    complete, pending = wait(pending, return_when=FIRST_COMPLETED)
                    for future in complete:
                        try:
                            result = future.result()
                        except BudgetExceededError as err:
                            for f in pending:
                                f.cancel()
                            return f"budget: {err}"
                        with write_lock:
                            append_jsonl(predictions_path, [result])
                            done[result.issue_ref] = result
                        finished += 1
                        if finished % 10 == 0 or finished == len(batch):
                            log(f"  {finished}/{len(batch)} issues")
            return None

        stopped = triage_all(todo, cfg.eval.concurrency)
        retry = [e for e in examples if _needs_run(done.get(e.snapshot.issue_ref))]
        if stopped is None and retry:
            # One slower pass for infrastructure failures (usually provider rate limits).
            log(f"retrying {len(retry)} infrastructure failures with 1 worker")
            stopped = triage_all(retry, 1)

    stats = clients[0].stats if clients else CallStats()
    write_cost(run_dir, stats)
    card: Scorecard | None = None
    if stopped is None and len(done) >= len(examples):
        predictions = [done[e.snapshot.issue_ref] for e in examples]
        card = score(
            examples, predictions, resamples=cfg.eval.bootstrap_resamples, seed=cfg.eval.seed
        )
        write_json(
            run_dir / "metrics.json",
            {"split": split, "config": cfg.name, **card.model_dump(mode="json")},
        )
        write_parquet(
            run_dir / "predictions.parquet",
            [
                {
                    **p.model_dump(mode="json", exclude={"label_confidence"}),
                    "label_confidence": json.dumps(p.label_confidence, sort_keys=True),
                }
                for p in predictions
            ],
        )
        if frozen is not None and session is not None:
            record(session, frozen, cfg, run_id, "completed")
    return RunOutcome(
        run_id=run_id,
        run_dir=run_dir,
        completed=len(done),
        total=len(examples),
        stopped_reason=stopped,
        scorecard=card,
        spent_usd=stats.cost_usd,
    )
