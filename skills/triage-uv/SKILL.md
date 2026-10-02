---
name: triage-uv
description: Triage a new astral-sh/uv GitHub issue - pick the kind label (bug, enhancement, question, documentation), area labels, the component (crate group) a fix would change, possible duplicates, and whether a reproduction is missing. Use for any issue filed against the uv repository.
license: MIT
metadata:
  repo: astral-sh/uv
  sources: GitHub label descriptions, the repository's issue forms and CONTRIBUTING.md, the crate layout at the freeze commit, train split statistics
---

# Triaging a uv issue

uv is a Python package and project manager written in Rust. You see the issue exactly as
it was first opened. Work in this order, and stop as soon as you can decide; most issues
need 2-6 tool calls.

## 1. Read the issue

uv has three issue forms, and the form shows in the headings: a bug report has
"Summary", "Platform" and "Version"; a feature request has "Summary" and "Example"; a
question starts with "Question". The form is the reporter's guess, not the answer:
- uv does something wrong (an error, a panic, a wrong resolution, a regression) -> **bug**;
- a new capability or an improvement to existing behaviour -> **enhancement**;
- "how do I...", "is this expected?", or a report where uv is working as designed and
  the reporter needs an explanation -> **question**, whatever form it was filed on;
- the documentation is wrong, unclear or missing -> **documentation**.

## 2. Look for a duplicate

Call `search_similar_issues` with 1-3 focused queries: the exact error message, then
"<command> <symptom>" (for example "uv sync lockfile extras"). Open a promising hit with
`get_issue` before claiming it. Read `references/duplicate_policy.md` if you are unsure.

## 3. Find the code a fix would change

The component is the group of crates a fix would edit. `search_code` for the error text,
the option name or the function tells you which crate under `crates/` holds the
behaviour. Crate groups and common traps: `references/component_map.md`.

## 4. Choose labels

- exactly one kind label;
- `performance`, `compatibility`, `internal` or `security` only when that is what the
  issue is about;
- `area:` labels only from the allowed list given in the task, and only when the issue
  is clearly about that area.

Definitions and counter-examples: `references/label_taxonomy.md`.

## 5. Decide whether a reproduction is missing

uv's `needs-mre` label asks the reporter for a minimal reproducible example. Checklist:
`references/needs_info_checklist.md`.

## 6. Submit

Call `submit_triage` once. Give calibrated confidences: 0.9 means you expect to be right
9 times in 10. Draft the triage comment as described in `references/comment_style.md`.
