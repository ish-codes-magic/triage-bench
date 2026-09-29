---
name: triage-cpython
description: Triage a new python/cpython GitHub issue - pick type, area, topic and OS labels, the component (directory) that a fix would change, possible duplicates, and whether the reporter must supply more information. Use for any issue filed against the CPython repository.
license: MIT
metadata:
  repo: python/cpython
  sources: devguide.python.org/triage/labels, GitHub label descriptions, train split statistics
---

# Triaging a CPython issue

You see the issue exactly as it was first opened. Work in this order, and stop as soon as
you can decide; most issues need 2-6 tool calls.

## 1. Read the issue

Note the module, function, syntax or tool involved, and what went wrong:
- the interpreter died (segfault, abort, `Fatal Python error`, assertion in a debug build) -> a **crash**;
- a wrong result, an unexpected exception, a hang, a regression -> a **bug**;
- a request for new behaviour or an API change -> a **feature**;
- wording, examples or missing documentation only -> **docs**.

## 2. Look for a duplicate

Call `search_similar_issues` with 1-3 focused queries: the exact error message, then
"<module> <symptom>". Open a promising hit with `get_issue` before claiming it.
Read `references/duplicate_policy.md` if you are unsure; wrongly closing a real report
costs more than missing a duplicate.

## 3. Find the code a fix would change

The component is the directory a fix would edit, not the topic of the report.
`search_code` for the named function or module tells you whether it is Python (`Lib/`),
C (`Modules/`) or the core (`Objects/`, `Python/`, `Parser/`, ...).
Directory rules and common traps: `references/component_map.md`.

## 4. Choose labels

- exactly one type label;
- the area label(s) that match where the fix goes (usually the same as the component);
- topic and OS labels only when the issue is clearly about them.

Definitions and counter-examples: `references/label_taxonomy.md`.

## 5. Decide whether information is missing

CPython's `pending` label means maintainers would close the issue unless the reporter
answers. Checklist: `references/needs_info_checklist.md`.

## 6. Submit

Call `submit_triage` once. Give calibrated confidences: 0.9 means you expect to be
right 9 times in 10. Draft the triage comment as described in
`references/comment_style.md`.
