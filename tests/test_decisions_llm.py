"""The LLM decision backend: verbalized and logprob confidences, abstentions, errors."""

import math
from pathlib import Path

import pytest

from triagelab.config import LLMConfig
from triagelab.cost import Usage
from triagelab.decisions.base import DecisionError
from triagelab.decisions.llm import ConfidenceMode, LLMDecisionBackend, letter_distribution
from triagelab.llm_client import Completion, TokenLogprob

from .fakes import FAKE_MODEL, FakeBackend, make_client

OPTIONS = ["type-bug", "type-crash", "type-feature"]


def lp(*pairs: tuple[str, float]) -> tuple[TokenLogprob, ...]:
    return tuple(TokenLogprob(token=t, logprob=v) for t, v in pairs)


def reply(text: str = "", logprobs: tuple[TokenLogprob, ...] = ()) -> Completion:
    return Completion(
        text=text,
        resolved_model="fake",
        usage=Usage(tokens_in=100, tokens_out=1),
        first_token_logprobs=logprobs,
    )


def backend(
    tmp_path: Path, mode: ConfidenceMode, *replies: Completion
) -> tuple[LLMDecisionBackend, FakeBackend]:
    fake = FakeBackend(script=list(replies))
    llm = LLMConfig(model=FAKE_MODEL, max_tokens=50, reasoning="none")
    return LLMDecisionBackend(make_client(tmp_path, fake), llm, mode), fake


def test_letter_variants_are_pooled_and_renormalised() -> None:
    top = lp(("B", -0.1), (" B", -3.0), ("A", -2.7), ("The", -5.0), ("Z", -1.0), ("b", -6.0))
    dist = letter_distribution(top, 3)
    b = math.exp(-0.1) + math.exp(-3.0) + math.exp(-6.0)
    a = math.exp(-2.7)
    assert dist[1] == pytest.approx(b / (a + b))  # "The" and the out-of-range "Z" are ignored
    assert dist[0] == pytest.approx(a / (a + b))
    assert 2 not in dist
    assert letter_distribution(lp(("The", -0.1)), 3) == {}


def test_logprob_choice(tmp_path: Path) -> None:
    top = lp(("B", -0.1), ("A", -2.7))
    b, fake = backend(tmp_path, "logprobs", reply("B", top))
    d = b.choose("<issue>x</issue>", "Which type?", OPTIONS)
    assert d.answer == "type-crash"
    assert d.confidence == pytest.approx(math.exp(-0.1) / (math.exp(-0.1) + math.exp(-2.7)))
    assert set(d.distribution) == {"type-bug", "type-crash"}
    assert d.backend == "llm-logprobs"
    assert d.cost_usd > 0
    request = fake.requests[0]
    assert request.top_logprobs == 20
    assert request.max_tokens == 2
    assert "A) type-bug\nB) type-crash\nC) type-feature" in request.messages[1].content


def test_logprobs_without_an_option_letter_abstain(tmp_path: Path) -> None:
    b, _ = backend(tmp_path, "logprobs", reply("The", lp(("The", -0.1))))
    d = b.choose("s", "q", OPTIONS)
    assert (d.answer, d.confidence) == ("", 0.0)


def test_missing_logprobs_are_an_infrastructure_error(tmp_path: Path) -> None:
    b, _ = backend(tmp_path, "logprobs", reply("B"))
    with pytest.raises(RuntimeError, match="no logprobs"):
        b.choose("s", "q", OPTIONS)


def test_verbalized_choice_and_its_schema(tmp_path: Path) -> None:
    b, fake = backend(tmp_path, "verbalized", reply('{"answer": "type-crash", "confidence": 0.7}'))
    d = b.choose("s", "q", OPTIONS)
    assert (d.answer, d.confidence, d.backend) == ("type-crash", 0.7, "llm-verbalized")
    schema = fake.requests[0].response_schema
    assert schema is not None
    assert schema["properties"]["answer"]["enum"] == OPTIONS


@pytest.mark.parametrize("text", ['{"answer": "type-made-up", "confidence": 0.9}', "not json"])
def test_an_invalid_verbalized_answer_abstains(tmp_path: Path, text: str) -> None:
    b, _ = backend(tmp_path, "verbalized", reply(text))
    d = b.choose("s", "q", OPTIONS)
    assert (d.answer, d.confidence) == ("", 0.0)


def test_yes_no_is_a_boolean(tmp_path: Path) -> None:
    b, _ = backend(tmp_path, "logprobs", reply("A", lp(("A", -0.2), ("B", -1.8))))
    d = b.yes_no("s", "Does it need more information?")
    assert d.answer is True
    assert d.confidence > 0.5


def test_numbers_need_verbalized_confidence(tmp_path: Path) -> None:
    b, _ = backend(tmp_path, "logprobs")
    with pytest.raises(DecisionError):
        b.score("s", "q", 0, 1)
    v, _ = backend(tmp_path, "verbalized", reply('{"value": 7, "confidence": 0.6}'))
    assert v.score("s", "q", 0, 5).answer == 5  # clipped into the range
