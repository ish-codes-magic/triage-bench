from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from triagelab.config import (
    AgentConfig,
    Config,
    LLMConfig,
    ProviderRoute,
    SystemConfig,
    deep_merge,
    load_config,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE = REPO_ROOT / "configs" / "base.yaml"


def test_base_config_loads_and_validates() -> None:
    cfg = load_config(BASE)
    assert cfg.name == "base"
    assert cfg.budget.usd_total == 150.0
    assert cfg.budget.usd_per_run == 5.0


def test_fingerprint_is_stable_and_sensitive() -> None:
    a = load_config(BASE)
    b = load_config(BASE)
    assert a.fingerprint() == b.fingerprint()
    changed = a.model_copy(update={"name": "other"})
    assert changed.fingerprint() != a.fingerprint()


def test_paths_serialize_identically_on_every_os() -> None:
    dumped = load_config(BASE).model_dump(mode="json")
    assert dumped["paths"]["prices_file"] == "configs/prices.yaml"
    assert dumped["cache"]["dir"] == ".cache/llm"


def test_route_tag_includes_quantization_when_pinned() -> None:
    assert ProviderRoute(provider="deepinfra", quantization="bf16").tag == "deepinfra/bf16"
    assert ProviderRoute(provider="alibaba").tag == "alibaba"


def test_route_is_rejected_for_non_openrouter_models() -> None:
    with pytest.raises(ValidationError, match="openrouter"):
        LLMConfig(model="openai/gpt-6-luna", route=ProviderRoute(provider="openai"))


def test_unknown_key_is_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "name: x\nbudget: {usd_total: 1, usd_per_run: 1}\nllm: {model: m, temprature: 0}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValidationError, match="temprature"):
        load_config(bad)


def test_inheritance_cycle_is_detected(tmp_path: Path) -> None:
    (tmp_path / "a.yaml").write_text("extends: b.yaml\n", encoding="utf-8")
    (tmp_path / "b.yaml").write_text("extends: a.yaml\n", encoding="utf-8")
    with pytest.raises(ValueError, match="cycle"):
        load_config(tmp_path / "a.yaml")


# ---- deep_merge ------------------------------------------------------------------------


def test_deep_merge_disjoint_keys_are_combined() -> None:
    assert deep_merge({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}


def test_deep_merge_nested_dicts_merge_recursively() -> None:
    base = {"llm": {"model": "m1", "max_tokens": 100}, "name": "base"}
    override = {"llm": {"model": "m2"}}
    assert deep_merge(base, override) == {"llm": {"model": "m2", "max_tokens": 100}, "name": "base"}


def test_deep_merge_lists_and_none_replace() -> None:
    base: dict[str, Any] = {"tools": ["a", "b"], "seed": 7}
    override: dict[str, Any] = {"tools": ["c"], "seed": None}
    assert deep_merge(base, override) == {"tools": ["c"], "seed": None}


def test_deep_merge_does_not_mutate_inputs() -> None:
    base = {"llm": {"model": "m1"}}
    override = {"llm": {"max_tokens": 5}}
    result = deep_merge(base, override)
    result["llm"]["model"] = "changed"
    assert base == {"llm": {"model": "m1"}}
    assert override == {"llm": {"max_tokens": 5}}


def test_deep_merge_result_shares_nothing_with_base() -> None:
    # "retry" exists only in base: a shallow copy would hand back base's own dict.
    base = {"retry": {"max_attempts": 4}, "tools": ["a"]}
    result = deep_merge(base, {})
    result["retry"]["max_attempts"] = 99
    result["tools"].append("b")
    assert base == {"retry": {"max_attempts": 4}, "tools": ["a"]}


def test_experiment_config_overrides_base(tmp_path: Path) -> None:
    exp = tmp_path / "exp.yaml"
    exp.write_text(
        f"extends: {BASE.as_posix()}\nname: exp\nllm: {{max_tokens: 64}}\n", encoding="utf-8"
    )
    cfg: Config = load_config(exp)
    assert cfg.name == "exp"
    assert cfg.llm.max_tokens == 64
    assert cfg.llm.model == load_config(BASE).llm.model  # inherited, not dropped


def test_agent_kind_and_agent_block_go_together() -> None:
    assert SystemConfig(kind="agent", agent=AgentConfig()).agent is not None
    with pytest.raises(ValidationError, match=r"system.agent"):
        SystemConfig(kind="agent")
    with pytest.raises(ValidationError, match=r"system.agent"):
        SystemConfig(kind="classifier", agent=AgentConfig())
