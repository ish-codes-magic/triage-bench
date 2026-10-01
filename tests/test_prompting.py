"""Repository-specific prompt wording comes from the profile, not from code (ADR-0047)."""

from pathlib import Path

from triagelab.baselines.llm_single_shot import SYSTEM_PROMPT
from triagelab.data.profile import PromptWording, load_profile
from triagelab.prompting import vocabulary

REPOS = Path(__file__).resolve().parents[1] / "configs" / "repos"
CPYTHON = load_profile(REPOS / "python__cpython.yaml")
UV = load_profile(REPOS / "astral-sh__uv.yaml")


def test_cpython_keeps_the_wording_its_cached_prompts_were_built_with() -> None:
    text = vocabulary(CPYTHON, ["topic-asyncio"])
    assert text.startswith(
        "Allowed labels. Copy them exactly as written; area labels have no prefix "
        '(write "stdlib", never "area-stdlib").\n'
    )
    assert "\nArea labels (any that apply): stdlib," in text
    assert "\nTopic and OS labels (any that apply): topic-asyncio\n" in text
    system = SYSTEM_PROMPT.format(repo="r", labels=CPYTHON.wording.single_shot_labels)
    assert "(normally one type-* label, plus area/topic/OS labels that clearly apply)" in system


def test_uv_is_not_told_cpythons_rules() -> None:
    text = vocabulary(UV, ["area:windows"])
    assert "no prefix" not in text
    assert "stdlib" not in text
    assert "Topic and OS" not in text
    assert '"area:" is part of an area label\'s name' in text
    assert "\nArea labels (any that apply): area:windows\n" in text


def test_a_profile_without_wording_gets_neutral_words() -> None:
    assert PromptWording().label_note == ""
    bare = CPYTHON.model_copy(update={"wording": PromptWording()})
    text = vocabulary(bare, ["x"])
    assert text.startswith("Allowed labels. Copy them exactly as written.\n")
