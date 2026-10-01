"""Adapter tests using LiteLLM's built-in `mock_response`: offline, no API key, no spend."""

import pytest
from litellm.exceptions import AuthenticationError, BadRequestError, RateLimitError

from triagelab.config import ProviderRoute
from triagelab.litellm_backend import LiteLLMBackend, build_params, wire_message
from triagelab.llm_client import LLMRequest, Message, ToolCall, ToolSpec

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


TOOL = ToolSpec(
    name="get_issue",
    description="Fetch one past issue.",
    parameters={"type": "object", "properties": {"number": {"type": "integer"}}},
)


def test_mock_tool_calls_are_parsed_with_raw_arguments() -> None:
    backend = LiteLLMBackend(
        extra_params={
            "mock_response": "",
            "mock_tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "get_issue", "arguments": '{"number": 1}'},
                }
            ],
        }
    )
    completion = backend.complete(REQUEST.model_copy(update={"tools": (TOOL,)}), timeout_s=5)
    assert completion.tool_calls == (
        ToolCall(id="call_1", name="get_issue", arguments='{"number": 1}'),
    )


def test_tools_and_forced_tool_choice_use_the_openai_wire_format() -> None:
    forced = REQUEST.model_copy(update={"tools": (TOOL,), "tool_choice": "get_issue"})
    params = build_params(forced, timeout_s=5)
    assert params["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "get_issue",
                "description": "Fetch one past issue.",
                "parameters": TOOL.parameters,
            },
        }
    ]
    assert params["tool_choice"] == {"type": "function", "function": {"name": "get_issue"}}
    assert "parallel_tool_calls" not in params  # unlisted by our endpoints: routing would fail
    auto = build_params(forced.model_copy(update={"tool_choice": "auto"}), timeout_s=5)
    assert auto["tool_choice"] == "auto"
    assert "tools" not in build_params(REQUEST, timeout_s=5)


def test_tool_turns_are_sent_in_the_openai_message_format() -> None:
    call = ToolCall(id="call_1", name="get_issue", arguments='{"number": 1}')
    assert wire_message(Message(role="user", content="hi")) == {"role": "user", "content": "hi"}
    assert wire_message(Message(role="assistant", content="", tool_calls=(call,))) == {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "get_issue", "arguments": '{"number": 1}'},
            }
        ],
    }
    assert wire_message(Message(role="tool", content="{}", tool_call_id="call_1")) == {
        "role": "tool",
        "content": "{}",
        "tool_call_id": "call_1",
    }


def test_top_logprobs_are_requested_and_parsed() -> None:
    from types import SimpleNamespace

    from triagelab.litellm_backend import (
        _first_token_logprobs,  # pyright: ignore[reportPrivateUsage]
    )

    request = LLMRequest(model="m", messages=(Message(role="user", content="x"),), max_tokens=1)
    assert "logprobs" not in build_params(request, timeout_s=5)
    assert "top_logprobs" not in request.model_dump()  # old cache keys are unchanged
    asked = request.model_copy(update={"top_logprobs": 5})
    params = build_params(asked, timeout_s=5)
    assert (params["logprobs"], params["top_logprobs"]) == (True, 5)
    assert asked.cache_key() != request.cache_key()

    top = [SimpleNamespace(token="B", logprob=-0.1), SimpleNamespace(token="A", logprob=-2.7)]
    choice = SimpleNamespace(logprobs=SimpleNamespace(content=[SimpleNamespace(top_logprobs=top)]))
    parsed = _first_token_logprobs(choice)
    assert [(t.token, t.logprob) for t in parsed] == [("B", -0.1), ("A", -2.7)]
    assert _first_token_logprobs(SimpleNamespace(logprobs=None)) == ()
