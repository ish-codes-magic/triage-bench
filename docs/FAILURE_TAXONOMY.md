# Failure taxonomy

**Status: v1.** Consolidated from open coding of 60 failures of the iteration-5 agent (`20260930-000255-agent-cf734a`) against the adjudicated dev labels. 20 open codes became 10 categories. The machine-readable version is `configs/failures/taxonomy.yaml`.

**Provenance.** The open coding was done by the model annotator (Claude Opus 5.5) at the owner's request (ADR-0035), and the LLM tagger is GPT-6 Luna. "Reference" below means the annotator's tags.

## Method (AGENTS.md §12.6, ADR-0033)

1. **Find failures.** Per issue and task, predictions are compared with the adjudicated labels (`eval/failures.py`). 72 of 97 dev issues have at least one.
2. **Open coding.** Each failure is shown with the issue and a compact agent trace, and tagged with short free-form codes. The §12.6 seed codes were offered; new codes were invented and reused.
3. **Consolidate.** Codes that share a root cause were merged into one category.
4. **Validate the tagger.** `failures tag` has an LLM tag the same run, and `failures validate` compares it with the reference, per category (κ on presence). A category counts as validated at κ ≥ 0.6.
5. **Report.** `runs stats` prints the tagger's counts for the whole run.

## v1 categories

| category | absorbs (open codes) | reference (60) | tagger (72) | tagger κ |
|---|---|---|---|---|
| **topic/OS over-labeling** | over-labeling topics, OS label from mention | 28 | 42 | 0.74 ✓ |
| **code-location confusion** | C vs Python area confusion, symptom location vs fix location, missing secondary area label | 24 | 31 | 0.83 ✓ |
| **type-label error** | crash vs bug confusion, type label confusion, missing type label | 17 | 20 | 0.88 ✓ |
| **repository guidance unused** | skill not loaded, skill misapplied | 16 | 2 | 0.09 ✗ |
| **correct evidence ignored** | correct evidence ignored | 10 | 14 | 0.62 ✓ |
| **duplicate retrieval error** | retrieval miss, duplicate under-called, related issue taken as duplicate, original outside index window | 9 | 13 | 0.88 ✓ |
| **ground-truth noise** | ground-truth noise | 9 | 0 | 0.00 ✗ |
| **search process failure** | stopped too early, budget exhaustion | 6 | 13 | −0.03 ✗ |
| **needs-info over-flagging** | needs-info over-flagging | 3 | 6 | 0.85 ✓ |
| **hallucinated file or label** | hallucinated file or label | 2 | 1 | 0.00 ✗ |

Two seed categories never occurred and were dropped: "wrong component map" and "output validation failure" (the latter was prevented by the M4 null-duplicate fix).

## What each category looks like

- **topic/OS over-labeling:**
  - `OS-linux` on a platform-independent `sum()` dealloc bug, because the issue template said Linux (#150868);
  - `topic-IO` was the added label in 9 of the 17 topic cases.
- **code-location confusion:**
  - `math` is a C module (the issue cites `mathmodule.c`), but it was labeled `stdlib` after 11 searches and no code search (#150534);
  - a speed-up missing `performance` (#150717).
- **type-label error:** access-violation crashes labeled `type-bug` (#150454); a docs issue submitted with no type label at all (#150506).
- **repository guidance unused:** a rule stated in the CPython skill was broken, and the skill wasn't read:
  - "exactly one type";
  - "segfault = crash";
  - "regression = bug";
  - "speed-up = feature + performance".

  In the 5 traces where the taxonomy *was* read, 4 still added OS or topic labels on mentions.
- **correct evidence ignored:** the agent retrieved an analogous refactor, #139098 (`type-refactor`), yet labeled `type-feature` (#150097).
- **duplicate retrieval error:**
  - the true original was retrieved and read but not flagged (#151030);
  - a pre-2024 original sat outside the indexed history (#151311).
- **ground-truth noise:** `topic-C-API` for a refleak in about 16 C-API functions is defensible, but the gold omits it (#150379).
- **search process failure:** all 12 steps went to near-identical code searches, ending with no answer (#150557).

## What it says about the agent

- **Most errors are label-taxonomy judgement, not retrieval.** Over-labeling, location confusion and type errors make up 69 of the 124 reference tags. Retrieval errors (9) are comparatively rare.
- **The rules that would prevent them are in the skill,** which this 9B model neither loads unprompted nor follows when made to (iteration 4).
- **The LLM tagger reproduces the frequent, observable categories reliably** (κ 0.62–0.88). It can't judge the ones that need outside knowledge: whether the skill states the broken rule, or whether the gold is debatable. Treat those counts as unvalidated.
