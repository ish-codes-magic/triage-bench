# uv label taxonomy

Copy label names exactly. Definitions in quotes are the repository's own label
descriptions.

## Kind labels: exactly one

| label | definition | counter-examples |
|---|---|---|
| `bug` | "Something isn't working" | uv fails, panics, resolves wrongly, or regressed between versions. Not a bug: uv doing what its documentation says, even if the reporter expected otherwise. |
| `enhancement` | "New feature or improvement to existing functionality" | A new command, flag or setting; better output; support for another platform or format. A request to change documented behaviour is an enhancement, not a bug. |
| `question` | "Asking for clarification or support" | "How do I...", "is this expected?", "why does uv...". Also a report filed as a bug where the behaviour is intended and the reporter needs an explanation. |
| `documentation` | "Improvements or additions to documentation" | Wrong, unclear or missing docs. A question that the docs already answer is a `question`. |

The issue form sets a first label (`bug`, `enhancement` or `question`), and maintainers
correct it. In the training data, the correction made most often by far is to
`question`: many bug-form reports are usage questions or intended behaviour. When the
report shows no uv defect, prefer `question`.

In the training data: `bug` 31%, `question` 29%, `enhancement` 24%, `documentation` 2%;
the rest have no kind label.

## Other labels: only when the issue is about them

| label | definition |
|---|---|
| `performance` | uv is slow or uses too much memory, disk or network. Combine with a kind label. |
| `compatibility` | "Compatibility with a specification or another tool" (a PEP, pip, Poetry, a lockfile or index format). |
| `internal` | "A refactor or improvement that is not user-facing". Rare on user-filed issues. |
| `security` | A security problem or hardening request. |

## Area labels (`area:`): only from the allowed list, only when clearly applicable

Maintainers apply area labels sparingly: most issues have none. The allowed list is
given in the task. The frequent ones:

| label | definition |
|---|---|
| `area:error-messages` | "Messaging when something goes wrong": the error is confusing, misleading or missing a hint. The problem is the *message*, not the failure itself. |
| `area:windows` | "Specific to the Windows platform": it fails on Windows and would not elsewhere. A report that merely comes from a Windows machine does not qualify. |
| `area:build-backend` | The `uv_build` build backend: building wheels and source distributions with uv's own backend. |
| `area:configuration` | "Settings and such": `uv.toml`, `[tool.uv]`, environment variables, precedence between them. |

Do not add an area label just because a word appears in the issue. A platform named in
the bug form's "Platform" field is the reporter's environment, not the topic.
