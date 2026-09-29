"""Adapter tests using LiteLLM's built-in `mock_response`: offline, no API key, no spend."""

import pytest
from litellm.exceptions import AuthenticationError, BadRequestError, RateLimitError

from triagelab.config import ProviderRoute
from triagelab.litellm_backend import LiteLLMBackend, build_params
from triagelab.llm_client import LLMRequest, Message

REQUEST = LLMRequest(
    model="openai/gpt-6-luna", messages=(Message(role="user", content="ping"),), max_tokens=16
)


def test_mock_completion_maps_text_and_usage() -> None:
    backend = LiteLLMBackend(extra_params={"mock_response": "pong"})
    completion = backend.complete(REQUEST, timeout_s=5)
    assert completion.text == "pong"
    # LiteLLM's mock reports fixed usage of 10 prompt / 20 completion tokens.
    assert completion.usage.tokens_in == 10
    assert completion.usage.tokens_out == 20


def test_rate_limit_is_retryable() -> None:
    backend = LiteLLMBackend(extra_params={"mock_response": "litellm.RateLimitError"})
    with pytest.raises(RateLimitError) as info:
        backend.complete(REQUEST, timeout_s=5)
    assert backend.is_retryable(info.value)


def test_bad_request_and_auth_are_not_retryable() -> None:
    backend = LiteLLMBackend()
    bad = BadRequestError(message="bad", model="m", llm_provider="openai")
    auth = AuthenticationError(message="no key", llm_provider="openai", model="m")
    assert not backend.is_retryable(bad)
    assert not backend.is_retryable(auth)


def test_retry_after_is_none_without_a_response() -> None:
    assert LiteLLMBackend().retry_after_s(RuntimeError("boom")) is None


def test_unrouted_request_sends_no_provider_preferences() -> None:
    assert "extra_body" not in build_params(REQUEST, timeout_s=5)


def test_routed_request_pins_one_provider_and_precision() -> None:
    routed = REQUEST.model_copy(
        update={
            "model": "openrouter/qwen/qwen3.5-9b",
            "route": ProviderRoute(provider="deepinfra", quantization="bf16"),
        }
    )
    params = build_params(routed, timeout_s=5)
    assert params["extra_body"] == {
        "provider": {
            "only": ["deepinfra"],
            "quantizations": ["bf16"],
            "allow_fallbacks": False,
            "require_parameters": True,
        }
    }
    assert params["num_retries"] == 0


def test_reasoning_effort_goes_to_openrouter_extra_body() -> None:
    routed = REQUEST.model_copy(
        update={
            "model": "openrouter/qwen/qwen3.5-9b",
            "route": ProviderRoute(provider="deepinfra", quantization="bf16"),
            "reasoning": "none",
        }
    )
    body = build_params(routed, timeout_s=5)["extra_body"]
    assert body["reasoning"] == {"effort": "none"}
    assert body["provider"]["only"] == ["deepinfra"]


def test_default_reasoning_sends_nothing() -> None:
    params = build_params(REQUEST, timeout_s=5)
    assert "reasoning_effort" not in params
    assert "extra_body" not in params
