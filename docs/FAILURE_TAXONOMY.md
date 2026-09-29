# Failure taxonomy

**Status: v0 (seed categories).** It is consolidated to v1 after the owner's open coding of about 50 agent failures. The machine-readable version is `configs/failures/taxonomy.yaml`; this page adds the method and examples.

## Method (AGENTS.md §12.6, ADR-0033)

1. **Find failures.** `eval/failures.py` compares a run's predictions with the truth (gold where adjudicated, silver otherwise) per issue and task. Each difference is readable, for example `T1: missing: stdlib; extra: docs`.
2. **Open coding.** In `triagelab label` → *Review failures*, the owner reads each failure next to the agent's trace and tags it with free-form codes. The seed codes below are offered, and new codes can be created.
3. **Consolidate.** Codes are merged into 6–10 categories. Each category lists the codes it absorbs, a definition and one or two example traces.
4. **Validate the tagger.** `triagelab failures tag` has an LLM tag the same run, and `failures validate` reports per-category κ against the owner's mapped codes. Only a validated tagger labels the remaining failures.
5. **Report.** `runs stats` prints the category counts of every tagged run, and each iteration in `docs/ITERATIONS.md` reports how the counts changed.

## v0 categories (the seed list)

| category | definition |
|---|---|
| retrieval miss | The information needed (an earlier issue, the right code) was never retrieved. |
| correct evidence ignored | A tool returned the right answer, but the final decision didn't use it. |
| skill not loaded | The repository skill would have prevented the error, but it was never loaded. |
| skill misapplied | The skill was loaded, but its guidance was misread or not followed. |
| wrong component map | The code location was found but mapped to the wrong component. |
| stopped too early | The agent decided before gathering evidence it clearly needed. |
| hallucinated file or label | The answer names a file, issue or label that doesn't exist or wasn't seen. |
| budget exhaustion | The step or tool budget forced an answer before the agent had converged. |
| output validation failure | The answer failed schema validation, and the fallback was scored. |
| ground-truth noise | The system's answer is defensible; the recorded truth is wrong or arbitrary. |

**Already visible in the M4 run, before any coding:**
- **skill not loaded:** the skill was loaded on 1 of 100 issues;
- **budget exhaustion:** 53 of 100 answers were forced.

Iterations 3–5 target these two directly.
