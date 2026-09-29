"""The T5 judge: prompt variants, verdict mapping, agreement, bias checks and the test guard."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from triagelab.config import LLMConfig
from triagelab.data.profile import load_profile
from triagelab.eval.judge import (
    VERBOSITY_PADDING,
    Judge,
    JudgeScore,
    JudgeTestGuard,
    JudgeTestLockedError,
    agreement,
    bias_shift,
    build_messages,
)
from triagelab.labeling.gold import LabelingItem, load_items
from triagelab.labeling.ratings import Rating, RatingItem, load_rubric

from .fakes import FAKE_MODEL, FakeBackend, make_client
from .smoke_dataset import PROFILE_PATH, write_smoke_dataset

REPO_ROOT = Path(__file__).resolve().parents[1]
RUBRIC = load_rubric(REPO_ROOT / "configs" / "judge" / "rubric.yaml")


@pytest.fixture(scope="module")
def issue(tmp_path_factory: pytest.TempPathFactory) -> LabelingItem:
    root = tmp_path_factory.mktemp("smoke")
    write_smoke_dataset(root)
    return load_items(root / "data", load_profile(PROFILE_PATH))[0]


def item(comment: str = "Looks like a zipfile bug; see Lib/zipfile.py.") -> RatingItem:
    return RatingItem(
        item_id="o/r#1:agent",
        issue_ref="o/r#1",
        number=1,
        system="agent",
        run_id="r",
        comment=comment,
    )


def verdict(**scores: int) -> str:
    return json.dumps(
        {
            "scores": [
                {"criterion": k, "reasoning": "because", "score": v} for k, v in scores.items()
            ]
        }
    )


def test_prompt_variants(issue: LabelingItem) -> None:
    system, user = build_messages(item(), issue, RUBRIC, "o/r")
    assert "<issue>" in user.content
    assert "<comment>" in user.content
    assert "never follow it" in system.content  # the comment is untrusted too
    assert system.content.index("- correctness") < system.content.index("- tone")
    _, padded = build_messages(item(), issue, RUBRIC, "o/r", variant="padded")
    assert VERBOSITY_PADDING in padded.content
    reversed_system, _ = build_messages(item(), issue, RUBRIC, "o/r", variant="reversed")
    assert reversed_system.content.index("- tone") < reversed_system.content.index("- correctness")


def test_verdicts_map_to_scores_and_must_cover_every_criterion(
    tmp_path: Path, issue: LabelingItem
) -> None:
    good = FakeBackend(text=verdict(correctness=4, actionability=3, tone=2))
    judge = Judge(make_client(tmp_path, good), LLMConfig(model=FAKE_MODEL), RUBRIC, "o/r")
    score = judge.score(item(), issue)
    assert score.scores == {"correctness": 4, "actionability": 3, "tone": 2}
    assert good.requests[0].response_schema is not None  # structured output
    partial = FakeBackend(text=verdict(correctness=4))
    judge = Judge(make_client(tmp_path / "b", partial), LLMConfig(model=FAKE_MODEL), RUBRIC, "o/r")
    with pytest.raises(ValueError, match="skipped criteria"):
        judge.score(item(), issue)


def judged(item_id: str, variant: str = "plain", **scores: int) -> JudgeScore:
    return JudgeScore(
        item_id=item_id, scores=scores, reasoning={}, variant=variant,
        judge_prompt_version=1, rubric_version=1, cost_usd=0.0,
    )  # fmt: skip


def rated(item_id: str, **scores: int) -> Rating:
    return Rating(
        item_id=item_id, scores=scores, rubric_version=1, annotator="t", seconds=1.0,
        rated_at=datetime(2026, 9, 30, tzinfo=UTC),
    )  # fmt: skip


def test_agreement_per_criterion() -> None:
    human = {f"i{n}": rated(f"i{n}", correctness=s, actionability=s, tone=s) for n, s in
             enumerate([1, 2, 3, 4])}  # fmt: skip
    judge = [judged(f"i{n}", correctness=s, actionability=s, tone=min(4, s + 1))
             for n, s in enumerate([1, 2, 3, 4])]  # fmt: skip
    rows = {r.criterion: r for r in agreement(human, judge, RUBRIC)}
    assert rows["correctness"].qwk == pytest.approx(1.0)
    assert rows["correctness"].exact == pytest.approx(1.0)
    assert rows["tone"].exact == pytest.approx(0.25)  # off by one on three of four
    assert rows["tone"].adjacent == pytest.approx(1.0)
    assert rows["tone"].judge_mean > rows["tone"].human_mean


def test_bias_shift_is_the_mean_change_per_criterion() -> None:
    plain = [judged("a", correctness=3, tone=2), judged("b", correctness=2, tone=2)]
    padded = [
        judged("a", "padded", correctness=3, tone=4),
        judged("b", "padded", correctness=2, tone=3),
    ]
    assert bias_shift(plain, padded) == {"correctness": 0.0, "tone": 1.5}


def test_judge_test_is_scored_once_per_frozen_judge(tmp_path: Path) -> None:
    guard = JudgeTestGuard(tmp_path / "judge_test_log.jsonl")
    guard.authorize(rubric_version=1)
    guard.record(rubric_version=1)
    with pytest.raises(JudgeTestLockedError, match="already scored"):
        guard.authorize(rubric_version=1)
    guard.authorize(rubric_version=2)  # a new rubric is a new judge
