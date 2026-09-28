"""Typed, layered run configuration.

Every run is described by one YAML file. An experiment file may declare
`extends: <path>` to inherit from a parent (usually `configs/base.yaml`) and override
only what differs, so each ablation is a small, readable diff against the baseline.

All models use `extra="forbid"`: a typo such as `temprature: 0` must fail loudly
rather than be silently ignored, because a silently ignored setting would invalidate
an ablation without anyone noticing.
"""

from pathlib import Path
from typing import Annotated, Any, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

from triagelab.hashing import stable_hash

# Serialize paths with forward slashes on every OS. Otherwise the same config would dump
# as `configs\prices.yaml` on Windows and `configs/prices.yaml` on Linux, and its
# fingerprint (and every cache key derived from it) would differ by machine.
PortablePath = Annotated[Path, PlainSerializer(lambda p: p.as_posix(), return_type=str)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BudgetConfig(_Strict):
    usd_total: float = Field(gt=0, description="Hard cap on spend across all runs, ever.")
    usd_per_run: float = Field(gt=0, description="Hard cap on spend within a single run.")


class LLMConfig(_Strict):
    """Model call settings.

    `temperature` and `seed` default to None, meaning "don't send it". Several current
    models reject any temperature other than their default, and seeds are deprecated or
    unsupported on most of them (see docs/DECISIONS.md, ADR-0004). Set them explicitly
    only for models that accept them.
    """

    model: str = Field(description="LiteLLM model string, e.g. 'anthropic/<model-id>'.")
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    seed: int | None = None
    max_tokens: int = Field(default=1024, gt=0)
    timeout_s: float = Field(default=60.0, gt=0)


class RetryConfig(_Strict):
    max_attempts: int = Field(default=4, ge=1)
    base_delay_s: float = Field(default=1.0, gt=0)
    max_delay_s: float = Field(default=30.0, gt=0)


class CacheConfig(_Strict):
    enabled: bool = True
    dir: PortablePath = Path(".cache/llm")


class PathsConfig(_Strict):
    runs_dir: PortablePath = Path("runs")
    prices_file: PortablePath = Path("configs/prices.yaml")


class Config(_Strict):
    name: str
    budget: BudgetConfig
    llm: LLMConfig
    retry: RetryConfig = RetryConfig()
    cache: CacheConfig = CacheConfig()
    paths: PathsConfig = PathsConfig()

    def fingerprint(self) -> str:
        """Short stable hash of the resolved config, recorded with every run."""
        return stable_hash(self.model_dump(mode="json"))[:12]


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Return a new dict with `override` layered on top of `base`.

    # YOUR TURN
    Rules:
      - A key present only in one input is copied through unchanged.
      - If both values are dicts, merge them recursively.
      - Otherwise the override value wins, including for lists (they are replaced,
        not concatenated) and for an explicit `None`.
      - Neither input may be mutated.

    Hint: build a fresh dict from `base`, then walk `override.items()`. Recursion handles
    the nesting; `isinstance(x, dict)` decides whether to recurse. Ask yourself why
    `dict(base)` alone is not enough to satisfy the no-mutation rule.
    Tests: tests/test_config.py::test_deep_merge_*
    """
    raise NotImplementedError("YOUR TURN: implement deep_merge (see docstring)")


def _load_raw(path: Path, seen: frozenset[Path] = frozenset()) -> dict[str, Any]:
    path = path.resolve()
    if path in seen:
        raise ValueError(f"Config inheritance cycle at {path}")
    raw: Any = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a YAML mapping at the top level")
    data = dict(cast(dict[str, Any], raw))  # our config files only use string keys
    parent = data.pop("extends", None)
    if parent is None:
        return data
    parent_raw = _load_raw(path.parent / str(parent), seen | {path})
    return deep_merge(parent_raw, data)


def load_config(path: Path) -> Config:
    """Load a YAML config, resolving `extends:` chains, and validate it."""
    return Config.model_validate(_load_raw(path))
