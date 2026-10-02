# Triage skills

Agent Skills for triaging a new GitHub issue, in the open [Agent Skills](https://agentskills.io) format: a folder with a `SKILL.md` (YAML front matter with `name` and `description`, then instructions) and optional `references/` files that are read on demand. They work with any agent that supports the format; this repository's own harness loads them with progressive disclosure (`src/triagelab/skills/loader.py`).

| Skill | For | Written by |
|---|---|---|
| [`triage-cpython`](triage-cpython/SKILL.md) | `python/cpython` | Hand, from the CPython devguide's label definitions |
| [`triage-uv`](triage-uv/SKILL.md) | `astral-sh/uv` | Hand, from the label descriptions, issue forms and crate layout. No evaluation issue was read. |
| [`triage-cpython-auto`](triage-cpython-auto/SKILL.md) | `python/cpython` | A script (`triagelab skills bootstrap`), from CONTRIBUTING, label descriptions and train-split statistics. No human edits. |
| [`generic-triage`](generic-triage/SKILL.md) | any repository | Hand; no repository knowledge. The control in the skills ablation. |

## What a repository skill contains

- `SKILL.md` (about 2,500 characters): the order of work, and how to decide the type label, duplicates, the component and whether information is missing.
- `references/label_taxonomy.md`: every label with its definition and counter-examples.
- `references/component_map.md`: directories mapped to components.
- `references/duplicate_policy.md`: when two issues are the same issue.
- `references/needs_info_checklist.md`: what a maintainer needs before starting.
- `references/comment_style.md`: how a draft triage comment should read.

Only the `name` and `description` are in the agent's context to begin with. The body enters when the agent calls `load_skill`, and a reference file when it calls `read_skill_file`.

## What they were measured to do

Honest numbers, from this project's ablation (E2, CPython dev split, adjudicated labels): **no skill variant changed label accuracy by a detectable amount** with the 9B model used here. The repository skill against no skill is +0.008 [−0.030, +0.049] micro-F1. Left to decide for itself, the model loaded a skill on 1–2% of issues; forcing the first call to `load_skill` put it in context every time and still did not help. Details: `reports/experiments/m6-ablations-gold.md` and `docs/ITERATIONS.md` (iteration 4).

So these skills are offered as careful, tested descriptions of two repositories' triage conventions, not as a proven accuracy gain. A larger model, or an agent that reads them more readily, may use them better; that is untested here.

## Use them elsewhere

Copy a skill folder into your agent's skills directory. The instructions refer to five tools by name (`search_similar_issues`, `get_issue`, `search_code`, `get_codeowners`, `list_components`); they are provided by the [`repo-intel` MCP server](../src/triagelab/mcp_server/README.md) in this repository. Without it, the label taxonomy and the checklists still apply.

To write one for another repository, start from `triage-uv`: it is the one written for a repository the harness had never seen, and `tests/test_skills_repo.py` holds every skill to the format.
