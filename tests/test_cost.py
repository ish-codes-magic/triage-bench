from datetime import date
from pathlib import Path

import pytest

from triagelab.config import load_config
from triagelab.cost import (
    BudgetExceededError,
    BudgetGuard,
    ModelPrice,
    UnknownModelPriceError,
    Usage,
    cost_usd,
    load_price_table,
    worst_case_cost_usd,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

# $2 in / $10 out / $0.20 cached, per 1M tokens: round numbers for hand-checking.
PRICE = ModelPrice(
    input_per_mtok=2.0,
    output_per_mtok=10.0,
    cached_input_per_mtok=0.2,
    source="test",
    verified_on=date(2026, 9, 29),
)


def test_cost_without_cache() -> None:
    # 1000 * 2/1e6 + 500 * 10/1e6 = 0.002 + 0.005
    assert cost_usd(Usage(tokens_in=1000, tokens_out=500), PRICE) == pytest.approx(0.007)


def test_cost_with_cached_prompt_tokens() -> None:
    # 200 uncached * 2 + 800 cached * 0.2 + 0 out, all / 1e6 = (400 + 160) / 1e6
    usage = Usage(tokens_in=1000, tokens_out=0, cached_tokens_in=800)
    assert cost_usd(usage, PRICE) == pytest.approx(0.00056)


def test_cached_rate_falls_back_to_input_rate() -> None:
    no_cache_price = PRICE.model_copy(update={"cached_input_per_mtok": None})
    usage = Usage(tokens_in=1000, tokens_out=0, cached_tokens_in=1000)
    assert cost_usd(usage, no_cache_price) == pytest.approx(0.002)


def test_worst_case_assumes_full_output_budget() -> None:
    # 1000 * 2/1e6 + 1024 * 10/1e6
    assert worst_case_cost_usd(1000, 1024, PRICE) == pytest.approx(0.01224)


def test_guard_refuses_call_that_would_break_run_cap() -> None:
    guard = BudgetGuard(per_run_usd=1.0, total_usd=100.0, spent_before_run_usd=0.0)
    guard.charge(0.95)
    guard.check(0.05)  # exactly at the cap is allowed
    with pytest.raises(BudgetExceededError, match="run cap"):
        guard.check(0.06)


def test_guard_refuses_call_that_would_break_total_cap() -> None:
    guard = BudgetGuard(per_run_usd=5.0, total_usd=150.0, spent_before_run_usd=149.5)
    assert guard.remaining_run_usd == pytest.approx(0.5)
    with pytest.raises(BudgetExceededError):
        guard.check(0.6)


def test_repo_price_table_loads_and_rejects_unknown_models() -> None:
    table = load_price_table(REPO_ROOT / "configs" / "prices.yaml")
    assert table.price_for("openai/gpt-6-luna").input_per_mtok == 0.10
    with pytest.raises(UnknownModelPriceError):
        table.price_for("nope/unknown-model")


def test_base_config_model_and_route_are_priced() -> None:
    cfg = load_config(REPO_ROOT / "configs" / "base.yaml")
    route = f"@{cfg.llm.route.tag}" if cfg.llm.route else ""
    table = load_price_table(REPO_ROOT / "configs" / "prices.yaml")
    table.price_for(f"{cfg.llm.model}{route}")  # raises if the default config is unpriced
