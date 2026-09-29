"""LiteLLM adapter: the only module in the codebase that imports `litellm`.

It translates our `LLMRequest` into a `litellm.completion` call and the response back
into our `Completion`. Everything provider-shaped stops here. Import it lazily (it
takes a few seconds), so commands that never call a model stay fast.

Behaviour we pin on purpose (verified against litellm 1.103.0; see ADR-0003):
  - Local metadata only. By default LiteLLM downloads its model price/capability map
    at import time, so its behaviour could change from one day to the next without a
    code change. We use the map bundled with the locked version instead.
  - `num_retries=0`: our retry loop is the only one, so every retry is visible.
  - `drop_params=False`: an unsupported parameter (e.g. `seed` on Anthropic) raises
    instead of being silently dropped, which would corrupt an ablation.
"""

import os

# These must be set before litellm is imported: it reads them at import time.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
os.environ.setdefault("LITELLM_LOCAL_ANTHROPIC_BETA_HEADERS", "True")

from typing import Any, cast

import litellm
from litellm.exceptions import AuthenticationError, BadRequestError

from triagelab.config import ProviderRoute
from triagelab.cost import Usage
from triagelab.llm_client import Completion, LLMRequest

litellm.suppress_debug_info = True
litellm.drop_params = False

# Transient by nature: timeout, conflict, rate limit. Every 5xx is also retried.
_RETRYABLE_STATUS = frozenset({408, 409, 429})


class LiteLLMBackend:
    def __init__(self, *, extra_params: dict[str, Any] | None = None) -> None:
        # `extra_params` exists for tests (e.g. LiteLLM's `mock_response`), not for callers.
        self._extra_params = extra_params or {}

    def complete(self, request: LLMRequest, *, timeout_s: float) -> Completion:
        params = {**build_params(request, timeout_s=timeout_s), **self._extra_params}
        # LiteLLM's response types are only partially annotated; treat the boundary as
        # untyped and validate everything we keep into our own pydantic models.
        response = cast(Any, litellm.completion(**params))
        return _to_completion(response)

    def is_retryable(self, err: Exception) -> bool:
        # BadRequestError also covers ContextWindowExceededError and UnsupportedParamsError:
        # sending the same request again cannot fix those.
        if isinstance(err, BadRequestError | AuthenticationError):
            return False
        status = getattr(err, "status_code", None)
        return isinstance(status, int) and (status in _RETRYABLE_STATUS or status >= 500)

    def retry_after_s(self, err: Exception) -> float | None:
        response = cast(Any, getattr(err, "response", None))
        headers = getattr(response, "headers", None)
        if headers is None:
            return None
        try:
            return float(headers.get("retry-after"))
        except (TypeError, ValueError):
            return None  # absent, or an HTTP-date we don't bother parsing


def build_params(request: LLMRequest, *, timeout_s: float) -> dict[str, Any]:
    """Translate our request into `litellm.completion` keyword arguments."""
    params: dict[str, Any] = {
        "model": request.model,
        "messages": [m.model_dump() for m in request.messages],
        # Always explicit: if omitted, LiteLLM fills in the model's maximum output.
        "max_tokens": request.max_tokens,
        "timeout": timeout_s,
        "num_retries": 0,
    }
    if request.temperature is not None:
        params["temperature"] = request.temperature
    if request.seed is not None:
        params["seed"] = request.seed
    if request.response_schema is not None:
        params["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": request.schema_name or "response",
                "schema": request.response_schema,
                "strict": True,
            },
        }
    extra_body: dict[str, Any] = {}
    if request.route is not None:
        # LiteLLM merges `extra_body` into the JSON it sends to OpenRouter.
        extra_body["provider"] = openrouter_provider_prefs(request.route)
    if request.reasoning != "default":
        if request.model.startswith("openrouter/"):
            # OpenRouter's unified control; "none" turns thinking off entirely.
            extra_body["reasoning"] = {"effort": request.reasoning}
        else:
            params["reasoning_effort"] = request.reasoning
    if extra_body:
        params["extra_body"] = extra_body
    return params


def openrouter_provider_prefs(route: ProviderRoute) -> dict[str, Any]:
    """OpenRouter's `provider` routing object that pins a call to exactly one endpoint.

    - `only` + `quantizations` select the provider and precision.
    - `allow_fallbacks: False` fails the call instead of silently using another provider.
    - `require_parameters: True` refuses providers that would drop one of our parameters
      (e.g. logprobs or the JSON schema) rather than quietly ignoring it.
    """
    prefs: dict[str, Any] = {
        "only": [route.provider],
        "allow_fallbacks": False,
        "require_parameters": True,
    }
    if route.quantization is not None:
        prefs["quantizations"] = [route.quantization]
    return prefs


def _to_completion(response: Any) -> Completion:
    usage = response.usage
    details = getattr(usage, "prompt_tokens_details", None)
    out_details = getattr(usage, "completion_tokens_details", None)
    hidden: dict[str, Any] = getattr(response, "_hidden_params", None) or {}
    return Completion(
        text=response.choices[0].message.content or "",
        resolved_model=getattr(response, "model", None),
        usage=Usage(
            # For Anthropic, LiteLLM's prompt_tokens already includes cache reads/writes.
            tokens_in=int(usage.prompt_tokens),
            tokens_out=int(usage.completion_tokens),
            cached_tokens_in=int(getattr(details, "cached_tokens", 0) or 0),
            reasoning_tokens=int(getattr(out_details, "reasoning_tokens", 0) or 0),
        ),
        litellm_cost_usd=hidden.get("response_cost"),
    )
