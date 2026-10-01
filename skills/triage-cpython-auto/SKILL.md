---
name: triage-cpython-auto
description: "Triage new python/cpython issues by selecting supported labels, identifying the likely component from the files a fix would change, checking for earlier duplicates, and deciding whether the reporter needs to provide specific missing information."
metadata:
  generated: "true, no human edits (E2 auto variant)"
  sources: "CONTRIBUTING, label descriptions, train split"
  prompt_version: "1"
---

# Triage workflow

1. Read the issue title, description, comments, and any reproduction or logs. Separate the reported behavior or request from the reporter’s suspected cause.
2. Decide whether the report is understandable enough to triage. If a missing detail prevents you from distinguishing the behavior, likely component, or a duplicate, request that specific detail; otherwise do not block triage on optional information.
3. Search earlier issues using distinctive phrases, API or module names, error text, and the reported version or platform. Read plausible matches and compare the actual behavior or requested change, not just matching keywords.
4. Record a possible duplicate only when an earlier issue appears to cover the same underlying behavior or request. Similar module names, symptoms, or platforms alone are not enough; if uncertain, report the candidate as uncertain rather than declaring it a duplicate.
5. Use code search to find the implementation, documentation, tests, or build/CI files related to the report. Identify the likely directory a fix would change; consult code owners as a cross-check, not as a substitute for identifying the files.
6. Choose the component from the likely fix location using [references/component_map.md](references/component_map.md). Do not choose based only on where the symptom appears or which files the reporter mentions.
7. Select only labels from [references/label_taxonomy.md](references/label_taxonomy.md). Apply a type label that matches the request or failure, and add component, platform, performance, or topic labels only when supported by the report or investigation.
8. Do not treat a feature request as a bug just because it concerns missing behavior; do not call a failure a crash unless the interpreter hard-crashes; and do not use a component label as a substitute for identifying the likely fix directory.
9. If information is needed, ask a focused question tied to the uncertainty (for example, the smallest missing reproduction or affected environment detail). Do not ask for details already supplied or for unrelated information.
10. Summarize the proposed labels, likely component, duplicate candidates (if any), and the precise information still needed. Mark uncertain conclusions as uncertain; do not invent labels outside the supplied vocabulary.
