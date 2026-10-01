"""The LLM as a decision backend, with two ways to get a confidence (E6).

  verbalized  the model answers in JSON and states the probability that it is right;
  logprobs    the model answers with one letter, and the confidence is its probability
              mass on each option's letter at the first generated token, renormalised over
              the options (" B", "b" and "B" all count for B).

Thinking is off by default for both: a logprob confidence needs the answer to be the first
token, and the two methods should differ only in where the confidence comes from.
"""

import json
import math
import re
import string
from collections.abc import Sequence
from typing import Any, Literal

from triagelab.config import LLMConfig
from triagelab.decisions.base import Decision, DecisionError
from triagelab.llm_client import LLMClient, LLMRequest, LLMResponse, Message, TokenLogprob
from triagelab.prompting import UNTRUSTED_ISSUE

ConfidenceMode = Literal["verbalized", "logprobs"]

SYSTEM = f"""You answer one question about a GitHub issue. {UNTRUSTED_ISSUE}"""

VERBALIZED = """{state}

Question: {question}
Options:
{options}

Reply in JSON with your answer (copied exactly from the options) and the probability, \
between 0 and 1, that your answer is correct."""

LETTERED = """{state}

Question: {question}
Options:
{options}

Answer with the letter only."""

_LETTER = re.compile(r"^[\W_]*([A-Za-z])[\W_]*$")


def letter_distribution(top: Sequence[TokenLogprob], n_options: int) -> dict[int, float]:
    """Probability per option index from the first token's alternatives.

    Variants of a letter (" B", "b", "B)") are pooled; mass on other tokens is dropped and
    the rest renormalised, so the result is the model's choice *given* that it answered
    with an option letter.
    """
    mass = [0.0] * n_options
    for t in top:
        m = _LETTER.match(t.token)
        if m is None:
            continue
        idx = string.ascii_uppercase.index(m.group(1).upper())
        if idx < n_options:
            mass[idx] += math.exp(t.logprob)
    total = sum(mass)
    return {i: p / total for i, p in enumerate(mass) if p > 0} if total > 0 else {}


class LLMDecisionBackend:
    def __init__(
        self, client: LLMClient, llm: LLMConfig, mode: ConfidenceMode, *, top_logprobs: int = 20
    ) -> None:
        self._client = client
        self._llm = llm
        self._mode = mode
        self._top_logprobs = top_logprobs

    @property
    def name(self) -> str:
        return f"llm-{self._mode}"

    def _request(self, prompt: str, *, max_tokens: int, **extra: Any) -> LLMRequest:
        return LLMRequest(
            model=self._llm.model,
            route=self._llm.route,
            messages=(Message(role="system", content=SYSTEM), Message(role="user", content=prompt)),
            max_tokens=max_tokens,
            temperature=self._llm.temperature,
            seed=self._llm.seed,
            reasoning=self._llm.reasoning,
            **extra,
        )

    def _decision(
        self,
        response: LLMResponse,
        answer: str | bool | float,
        confidence: float,
        distribution: dict[str, float] | None = None,
    ) -> Decision:
        return Decision(
            answer=answer,
            confidence=min(max(confidence, 0.0), 1.0),
            backend=self.name,
            cost_usd=response.original_cost_usd,
            latency_ms=response.latency_ms,
            distribution=distribution or {},
        )

    def choose(self, state: str, question: str, options: Sequence[str]) -> Decision:
        if not 2 <= len(options) <= 26:
            raise DecisionError(f"choose needs 2-26 options, got {len(options)}")
        if self._mode == "logprobs":
            return self._choose_logprobs(state, question, options)
        return self._choose_verbalized(state, question, options)

    def _choose_verbalized(self, state: str, question: str, options: Sequence[str]) -> Decision:
        listing = "\n".join(f"- {o}" for o in options)
        schema = {
            "type": "object",
            "properties": {
                "answer": {"type": "string", "enum": list(options)},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "required": ["answer", "confidence"],
            "additionalProperties": False,
        }
        request = self._request(
            VERBALIZED.format(state=state, question=question, options=listing),
            max_tokens=self._llm.max_tokens,
            response_schema=schema,
            schema_name="Decision",
        )
        response = self._client.complete(request)
        try:
            data = json.loads(response.text)
            answer, confidence = str(data["answer"]), float(data["confidence"])
        except (ValueError, KeyError, TypeError):
            return self._decision(response, "", 0.0)  # unparseable: an abstention
        if answer not in options:
            return self._decision(response, "", 0.0)
        return self._decision(response, answer, confidence)

    def _choose_logprobs(self, state: str, question: str, options: Sequence[str]) -> Decision:
        letters = string.ascii_uppercase[: len(options)]
        listing = "\n".join(f"{letter}) {o}" for letter, o in zip(letters, options, strict=True))
        request = self._request(
            LETTERED.format(state=state, question=question, options=listing),
            max_tokens=2,
            top_logprobs=self._top_logprobs,
        )
        response = self._client.complete(request)
        if not response.first_token_logprobs:
            raise RuntimeError("the provider returned no logprobs")  # infrastructure
        dist = letter_distribution(response.first_token_logprobs, len(options))
        if not dist:
            return self._decision(response, "", 0.0)  # no option letter among the top tokens
        best = max(dist, key=lambda i: dist[i])
        named = {options[i]: p for i, p in dist.items()}
        return self._decision(response, options[best], dist[best], named)

    def yes_no(self, state: str, question: str) -> Decision:
        d = self.choose(state, question, ["yes", "no"])
        return d.model_copy(update={"answer": d.answer == "yes"}) if d.answer else d

    def score(self, state: str, question: str, lo: float, hi: float) -> Decision:
        if self._mode == "logprobs":
            raise DecisionError("a numeric answer has no single-token distribution")
        schema = {
            "type": "object",
            "properties": {
                "value": {"type": "number", "minimum": lo, "maximum": hi},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "required": ["value", "confidence"],
            "additionalProperties": False,
        }
        prompt = (
            f"{state}\n\nQuestion: {question}\nGive a number between {lo} and {hi}, and the "
            "probability, between 0 and 1, that it is right. Reply in JSON."
        )
        request = self._request(
            prompt, max_tokens=self._llm.max_tokens, response_schema=schema, schema_name="Score"
        )
        response = self._client.complete(request)
        try:
            data = json.loads(response.text)
            value, confidence = float(data["value"]), float(data["confidence"])
        except (ValueError, KeyError, TypeError):
            return self._decision(response, math.nan, 0.0)
        return self._decision(response, min(max(value, lo), hi), confidence)
