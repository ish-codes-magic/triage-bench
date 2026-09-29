"""Typed, layered run configuration.

Every run is described by one YAML file. An experiment file may declare
`extends: <path>` to inherit from a parent (usually `configs/base.yaml`) and override
only what differs, so each ablation is a small, readable diff against the baseline.

All models use `extra="forbid"`: a typo such as `temprature: 0` must fail loudly
rather than be silently ignored, because a silently ignored setting would invalidate
an ablation without anyone noticing.
"""

import copy
from pathlib import Path
from typing import Annotated, Any, Self, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, model_validator

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


class ProviderRoute(_Strict):
    """Pins an OpenRouter model to one hosting provider, and optionally one precision.

    Left alone, OpenRouter load-balances each call across providers that may serve the
    "same" model at different precisions (fp4/fp8/bf16) and with different parameter
    support. In an evaluation that is a silent confound: the model could change from one
    call to the next. See ADR-0010.
    """

    provider: str = Field(description="OpenRouter provider slug, e.g. 'deepinfra'.")
    quantization: str | None = Field(default=None, description="e.g. 'bf16'; None = as served.")

    @property
    def tag(self) -> str:
        """The endpoint tag OpenRouter uses, e.g. 'deepinfra/bf16'."""
        return f"{self.provider}/{self.quantization}" if self.quantization else self.provider


class LLMConfig(_Strict):
    """Model call settings.

    `temperature` and `seed` default to None, meaning "don't send it". Several current
    models reject any temperature other than their default, and seeds are deprecated or
    unsupported on most of them (see docs/DECISIONS.md, ADR-0004). Set them explicitly
    only for models that accept them.
    """

    model: str = Field(description="LiteLLM model string, e.g. 'openrouter/qwen/qwen3.5-9b'.")
    route: ProviderRoute | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    seed: int | None = None
    max_tokens: int = Field(default=1024, gt=0)
    timeout_s: float = Field(default=60.0, gt=0)

    @model_validator(mode="after")
    def _route_needs_openrouter(self) -> Self:
        if self.route is not None and not self.model.startswith("openrouter/"):
            raise ValueError(f"llm.route only applies to openrouter/ models, not {self.model!r}")
        return self


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
    ledger_file: PortablePath = Path("runs/spend_ledger.jsonl")


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

    Rules:
      - A key present only in one input is copied through unchanged.
      - If both values are dicts, merge them recursively.
      - Otherwise the override value wins, including for lists (they are replaced,
        not concatenated) and for an explicit `None`.
      - Neither input is mutated, and the result shares no mutable objects with them.

    Lists replace rather than concatenate so that an experiment can *remove* an item
    (e.g. a tool) by restating the list. Concatenation could only ever add.
    """
    # deepcopy, not dict(base): a shallow copy shares nested dicts with `base`, so later
    # edits to the merged config would silently edit the parent config too.
    merged = copy.deepcopy(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = deep_merge(cast(dict[str, Any], current), cast(dict[str, Any], value))
        else:
            merged[key] = copy.deepcopy(value)
    return merged


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
