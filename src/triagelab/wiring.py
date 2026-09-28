"""Composition root: the one place that decides which concrete classes go together.

Everything else receives its collaborators as arguments, which is what lets tests
swap in a fake backend, a temp cache or a tiny budget without patching anything.
"""

from triagelab.cache import DiskCache
from triagelab.config import Config
from triagelab.cost import BudgetGuard, load_price_table
from triagelab.ledger import SpendLedger
from triagelab.llm_client import CompletionBackend, LLMClient


def build_llm_client(
    cfg: Config, *, run_id: str, backend: CompletionBackend | None = None
) -> LLMClient:
    """An `LLMClient` wired from config, with the all-time budget read from the ledger."""
    if backend is None:
        # Lazy import: litellm takes seconds to import, and most commands never call a model.
        from triagelab.litellm_backend import LiteLLMBackend

        backend = LiteLLMBackend()
    ledger = SpendLedger(cfg.paths.ledger_file)
    return LLMClient(
        backend=backend,
        prices=load_price_table(cfg.paths.prices_file),
        guard=BudgetGuard(
            per_run_usd=cfg.budget.usd_per_run,
            total_usd=cfg.budget.usd_total,
            spent_before_run_usd=ledger.total_usd(),
        ),
        ledger=ledger,
        cache=DiskCache(cfg.cache.dir) if cfg.cache.enabled else None,
        run_id=run_id,
        retry=cfg.retry,
        timeout_s=cfg.llm.timeout_s,
    )
