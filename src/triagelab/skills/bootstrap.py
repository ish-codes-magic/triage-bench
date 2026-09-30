"""Bootstrap a repository skill automatically (AGENTS.md §9, E2's "auto" variant).

Sources, and only these:
  - the frozen checkout's CONTRIBUTING file (from before the evaluation window);
  - the repository's label descriptions (GitHub labels API; metadata, not issues);
  - statistics from the **train** split only: label frequencies, a few example titles
    per label, component shares.

One structured model call turns them into SKILL.md plus two reference files. The output
is written as generated, with no human edits, so E2 can ask whether a hand-written skill
beats one a model wrote from the same public sources.
"""

import json
from collections import Counter, defaultdict
from pathlib import Path

import httpx
from pydantic import BaseModel, ConfigDict, Field

from triagelab.config import LLMConfig
from triagelab.data.profile import RepoProfile
from triagelab.eval.dataset import EvalExample
from triagelab.llm_client import LLMClient, LLMRequest, Message

BOOTSTRAP_PROMPT_VERSION = 1
EXAMPLES_PER_LABEL = 3


def fetch_label_descriptions(repo: str, token: str, cache: Path) -> dict[str, str]:
    """All of a repository's labels and their descriptions, cached on disk."""
    if cache.exists():
        return dict(json.loads(cache.read_text(encoding="utf-8")))
    labels: dict[str, str] = {}
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    url: str | None = f"https://api.github.com/repos/{repo}/labels?per_page=100"
    with httpx.Client(headers=headers, timeout=30) as client:
        while url:
            response = client.get(url)
            response.raise_for_status()
            for label in response.json():
                labels[str(label["name"])] = str(label.get("description") or "")
            url = response.links.get("next", {}).get("url")
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(labels, indent=1, sort_keys=True), encoding="utf-8")
    return labels


def collect_sources(
    profile: RepoProfile,
    train: list[EvalExample],
    family_labels: list[str],
    label_descriptions: dict[str, str],
    contributing: str,
) -> str:
    """The bootstrap's whole input, as one Markdown document (train split only)."""
    triaged = [e for e in train if e.gold.human_triaged]
    counts = Counter(label for e in triaged for label in e.gold.labels)
    examples: defaultdict[str, list[str]] = defaultdict(list)
    for e in triaged:
        for label in sorted(e.gold.labels):
            if len(examples[label]) < EXAMPLES_PER_LABEL:
                examples[label].append(e.snapshot.title)
    tax = profile.taxonomy
    vocabulary = [*tax.type, *tax.area, *family_labels]
    label_rows = "\n".join(
        f"- `{label}` ({counts[label]} of {len(triaged)} triaged train issues): "
        f"{label_descriptions.get(label) or '(no description)'}. Examples: "
        + "; ".join(f'"{t}"' for t in examples[label])
        for label in vocabulary
    )
    components = Counter(e.gold.component for e in train if e.gold.component)
    total = sum(components.values()) or 1
    component_rows = "\n".join(
        f"- `{c.name}`: files under {', '.join(c.prefixes)} "
        f"({components[c.name] / total:.0%} of fixed train issues)"
        for c in profile.components
    )
    return (
        f"# Repository: {profile.repo}\n\n"
        f"## CONTRIBUTING (from the repository)\n\n{contributing.strip()[:6000]}\n\n"
        f"## Labels (the allowed vocabulary), with descriptions and train statistics\n\n"
        f"{label_rows}\n\n"
        f"## Components (the directory a fix changes)\n\n{component_rows}\n"
    )


class GeneratedSkill(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(description="What the skill does and when to use it (<= 1000 chars).")
    body: str = Field(description="SKILL.md body in Markdown: a step-by-step triage workflow.")
    label_taxonomy: str = Field(description="references/label_taxonomy.md in Markdown.")
    component_map: str = Field(description="references/component_map.md in Markdown.")


SYSTEM = """You write Agent Skills: instructions an AI agent loads to do a task well. Write \
a skill for triaging new GitHub issues in {repo}: choosing labels from the allowed \
vocabulary, the component a fix would change, possible duplicates of earlier issues, and \
whether the reporter must provide more information.

Use only the sources the user gives you. Be concrete and brief: definitions, decision \
rules, and counter-examples an agent can apply. The body is a numbered workflow of at \
most 60 lines that points to references/label_taxonomy.md and references/component_map.md \
by those exact paths. The agent has tools to search earlier issues, read one, search the \
code, and look up code owners."""


def generate(client: LLMClient, llm: LLMConfig, repo: str, sources: str) -> GeneratedSkill:
    request = LLMRequest(
        model=llm.model,
        route=llm.route,
        messages=(
            Message(role="system", content=SYSTEM.format(repo=repo)),
            Message(role="user", content=sources),
        ),
        max_tokens=max(llm.max_tokens, 12_000),
        temperature=llm.temperature,
        seed=llm.seed,
        reasoning=llm.reasoning,
    )
    skill, _ = client.complete_structured(request, GeneratedSkill)
    return skill


def write_skill(skill: GeneratedSkill, directory: Path, *, sources_note: str) -> None:
    """Write the generated files exactly as generated (front matter aside)."""
    name = directory.name
    description = " ".join(skill.description.split())[:1000].replace('"', "'")
    front = (
        f"---\nname: {name}\n"
        f'description: "{description}"\n'
        "metadata:\n"
        '  generated: "true, no human edits (E2 auto variant)"\n'
        f'  sources: "{sources_note}"\n'
        f'  prompt_version: "{BOOTSTRAP_PROMPT_VERSION}"\n'
        "---\n\n"
    )
    (directory / "references").mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text(front + skill.body.strip() + "\n", encoding="utf-8")
    (directory / "references" / "label_taxonomy.md").write_text(
        skill.label_taxonomy.strip() + "\n", encoding="utf-8"
    )
    (directory / "references" / "component_map.md").write_text(
        skill.component_map.strip() + "\n", encoding="utf-8"
    )
