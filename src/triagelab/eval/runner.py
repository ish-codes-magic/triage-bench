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
from triagelab.config import Config
from triagelab.cost import BudgetExceededError
from triagelab.data.build import dataset_paths
from triagelab.data.profile import RepoProfile, load_profile
from triagelab.data.splits import Split
from triagelab.data.storage import append_jsonl, read_jsonl, write_json, write_parquet
from triagelab.eval.dataset import EvalExample, family_vocabulary, load_history, load_split
from triagelab.eval.registry import create_run, git_info, write_cost
from triagelab.eval.score import Scorecard, score
from triagelab.llm_client import CallStats, CassetteMissError, LLMClient
from triagelab.triage import Triager, TriageResult

TEST_EVALUATION_LIMIT = 2
INFRA_ERROR_PREFIX = "infra: "
Log = Callable[[str], None]


class TestSetLockedError(RuntimeError):
    """The test split was requested without permission, or its evaluation budget is spent."""

    __test__ = False  # not a pytest test class, despite the name


class TestSetGuard:
    """Policy as code: test-set evaluations need a flag and are capped and logged."""

    __test__ = False  # not a pytest test class, despite the name

    def __init__(self, runs_dir: Path) -> None:
        self._log = runs_dir / "test_evaluations.jsonl"

    def evaluations(self) -> list[dict[str, str]]:
        if not self._log.exists():
            return []
        return [
            json.loads(line) for line in self._log.read_text(encoding="utf-8").splitlines() if line
        ]

    def authorize(self, allow: bool) -> None:
        if not allow:
            raise TestSetLockedError(
                "The test split is locked. Iterate on dev; pass --allow-test only for the "
                "final evaluation (at most twice in the project, AGENTS.md §7.4)."
            )
        used = len(self.evaluations())
        if used >= TEST_EVALUATION_LIMIT:
            raise TestSetLockedError(f"Test set already evaluated {used} times (limit 2).")

    def record(self, run_id: str, config_name: str) -> None:
        self._log.parent.mkdir(parents=True, exist_ok=True)
        with self._log.open("a", encoding="utf-8", newline="\n") as f:
            f.write(
                json.dumps(
                    {"run_id": run_id, "config": config_name, "at": datetime.now(UTC).isoformat()}
                )
                + "\n"
            )


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
    client: Callable[[], LLMClient],
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
    if cfg.system.agent is not None:  # kind == "agent" (the config validator pairs them)
        from triagelab.harness.factory import build_agent  # MCP/OTel imports only when needed

        return build_agent(
            cfg,
            cfg.system.agent,
            profile,
            family_vocabulary(train, cfg.system.min_label_count),
            client(),
            max_body_chars=cfg.system.max_body_chars,
            run_id=run_id,
            run_dir=run_dir,
            stack=stack,
        )
    return LLMSingleShotTriager(
        client(),
        cfg.llm,
        profile,
        family_vocabulary(train, cfg.system.min_label_count),
        max_body_chars=cfg.system.max_body_chars,
    )


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
    allow_test: bool = False,
    resume_dir: Path | None = None,
) -> RunOutcome:
    test_guard = TestSetGuard(runs_dir)
    if split == "test":
        test_guard.authorize(allow_test)

    profile = load_profile(cfg.dataset.profile)
    examples = load_split(cfg.dataset.data_dir, profile, split)[:limit]
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
            },
        )
        run_id = manifest.run_id

    clients: list[LLMClient] = []

    def client() -> LLMClient:
        clients.append(wiring.build_llm_client(cfg, run_id=run_id))
        return clients[-1]

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
        if split == "test":
            test_guard.record(run_id, cfg.name)
    return RunOutcome(
        run_id=run_id,
        run_dir=run_dir,
        completed=len(done),
        total=len(examples),
        stopped_reason=stopped,
        scorecard=card,
        spent_usd=stats.cost_usd,
    )
