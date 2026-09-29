# Labeling guide

How the gold labels, comment ratings and failure tags in `data/gold/` are made. Open the app with:

```bash
uv run triagelab label            # opens http://localhost:8501; Ctrl+Enter submits a form
```

Everything saves as you go, so you can stop at any issue and continue later. The latest save per item wins, so fixing a mistake is just saving again.

---

## 1. Gold labels (page "Gold labels"): about 150 issues, about 1-2 min each

The **dev** split (100 issues) comes first. It's needed for iterating, the judge and the failure review. The **test** split (50 issues) is labeled once, before the one-time test evaluation.

### Blind pass: the issue as it was opened

You see only the title, body, author association and date, which is exactly what every system sees. Don't open the issue on GitHub in this pass: it shows the future (labels, comments, the fix).

| field | rule |
|---|---|
| **Type** (exactly one) | `type-bug` for wrong behaviour or an exception; `type-crash` only for a hard interpreter crash (segfault, abort, `Fatal Python error`); `type-feature` for new behaviour or an API change; `type-refactor` for no user-visible change; `type-security` for a vulnerability or hardening. |
| **Areas** | Where the fix would go: `stdlib` (Lib/, Python), `extension-modules` (Modules/, C), `interpreter-core` (Objects/, Python/, Parser/, ...), `docs`, `tests`, `build`, `infra`, and `performance` for speed or resources. |
| **Topic / OS** | Only when the issue is squarely about it (`topic-asyncio`, `OS-windows`, ...), not when it's just mentioned. |
| **Component** | The directory a fix would change. Choose "(can't tell)" rather than guess. |
| **Needs info** | Only if a maintainer couldn't start without an answer from the reporter: no reproducer, no error output, or an unknown version for a version-specific problem. |

The reference is the CPython skill's `skills/triage-cpython/references/label_taxonomy.md`, which uses the devguide's own definitions.

### Final pass: after "Save and reveal"

The evidence appears: the labels maintainers applied (and whether an author, a triager or a bot applied them), the fixing PRs with their files and the derived component, and any duplicate closure. The form starts from **your blind answer**, not from the evidence. Change it only where the evidence convinces you.

- **The gold is what's true, not what maintainers clicked.** A maintainer's label can be wrong or incomplete, and the derived component can be wrong (a PR that only adds a test). Disagreeing with the evidence is fine and valuable: it's how label noise is measured.
- **Duplicates:** keep the proposed original if the two issues share a root cause; clear it if they only share a topic.
- **Unusable:** tick it for spam, non-issues, or things no one could judge.
- **Notes:** use them for anything surprising; they help the failure analysis.

## 2. Comment ratings (page "Rate comments"): 100 comments, about 30-60 s each

Each dev issue has one draft triage comment, written by one of two systems. You aren't told which. Score each rubric criterion 1-4 using the level descriptions shown under it (`configs/judge/rubric.yaml`):

- **correctness:** Is everything it claims true, given the issue and what happened next?
- **actionability:** Does it move the issue forward, for example the right area, the specific missing information, or a concrete pointer?
- **tone:** Could a maintainer post it as it is?

Score what's written, not what you'd have written. A comment that is correct but vague is a 3, not a 1. About half of your ratings calibrate the LLM judge (judge-dev), and the other half measure it once (judge-test). The page doesn't show which half an item is in, so every rating counts the same.

## 3. Failure review (page "Review failures"): about 50 failures, about 1-2 min each

Choose the latest agent run. Each failure shows what differed (for example `T3: said docs, truth stdlib`), the issue, and the agent's trace step by step. Tag **why** it failed with one or more short codes:

- Start from the offered seed codes ("retrieval miss", "skill not loaded", "budget exhaustion", ...).
- When none fits, type a new one: that's open coding. Reuse your own new codes, so the vocabulary converges.
- "ground-truth noise" is a legitimate answer when the agent was right and the label wasn't.

After about 50 tags, the codes are merged into 6-10 categories (`docs/FAILURE_TAXONOMY.md`), and an LLM tagger is checked against your tags before it labels the rest.
