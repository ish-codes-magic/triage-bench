"""Every committed config resolves, and its model route has a verified price.

`extends:` deep-merges nested blocks, so a config that sets `route: {provider: openai}`
silently inherits base.yaml's `quantization: bf16` unless it says `quantization: null`.
The price table only lists real routes, so this test catches such a merge at review time
instead of at the first (refused) model call.
"""

from pathlib import Path

import pytest

from triagelab.config import load_config
from triagelab.cost import load_price_table
from triagelab.llm_client import LLMRequest

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIGS = sorted(
    p
    for folder in ("experiments", "judge", "gate")
    for p in (REPO_ROOT / "configs" / folder).glob("*.yaml")
    if p.name not in ("rubric.yaml", "gate.yaml")  # not experiment configs
)


@pytest.mark.parametrize("path", CONFIGS, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_config_resolves_to_a_priced_route(path: Path) -> None:
    cfg = load_config(path)
    prices = load_price_table(REPO_ROOT / cfg.paths.prices_file)
    request = LLMRequest(model=cfg.llm.model, route=cfg.llm.route, messages=(), max_tokens=1)
    prices.price_for(request.price_key())  # raises UnknownModelPriceError for a bad merge
