# M5: Gold labels, a calibrated judge, and a failure taxonomy

**What M5 built:** the reference side of evaluation (labels were produced by a model annotator at the owner's request; see ADR-0035).
- A labeling app with three pages (gold labels, comment ratings, failure review).
- Agreement metrics written by hand.
- Gold re-scoring, including a human baseline.
- An LLM judge for triage comments, with calibration, bias checks and a judge-test guard.
- An open-coding workflow that turns failure tags into a taxonomy, and a validated LLM tagger.

**Why it matters:** silver labels are derived from maintainer clicks and PR files. Until a person checks them, every number in this project could just be measuring label noise. And the triage comment (T5) has no ground truth at all, so without a judge that is *measured* against a human, T5 would be opinion.

```
triagelab label  ── Gold labels ── blind pass (issue as opened) ─► reveal evidence ─► final (gold)
                 ├─ Rate comments ─ 100 comments, system hidden, rubric 1-4 per criterion
                 └─ Review failures ─ failure diff + agent trace ─► open codes
data/gold/*.jsonl (committed) ─► results --labels gold   (every run re-scored + "human, blind" row)
                               ├► gold-report            (silver-vs-gold κ, blind-vs-final κ)
                               ├► judge calibrate        (QWK on judge-dev; judge-test once)
                               └► failures tag/validate  (LLM tagger κ vs your codes) ─► runs stats
```

---

## 1. Concepts, and where they live

| Concept | What to take away | Code |
|---|---|---|
| **Cohen's κ** | Agreement beyond chance: `(p_o − p_e)/(1 − p_e)`. 90% agreement on a label that is 90% "no" is κ ≈ 0. It is undefined when chance agreement is 1. | `eval/agreement.py`: `cohen_kappa` |
| **Quadratic-weighted κ** | For ordered scores: being off by 1 costs 1/9 of being off by 3 on a 1-4 scale. It's the standard for rubric agreement. | `agreement.py`: `weighted_kappa` |
| **Blind, then adjudicate** | Label from the model's own inputs first, then with the evidence. One session gives gold labels, a human baseline, and a measure of anchoring. | `labeling/gold.py`, `gold_page.py` |
| **Gold re-scoring** | Predictions are stored, so re-scoring against new labels is free. A person's blind pass is just another system. | `eval/gold_labels.py`, `eval/report.py`: `rescore_on_gold` |
| **Judge calibration** | Tune on judge-dev, report once on judge-test, and freeze and version the prompt. It's the same discipline as dev/test. | `eval/judge.py`: `JudgeTestGuard` |
| **Reason-then-score** | The judge explains before it scores, which grounds the number in a stated reason. | `judge.py`: `CriterionScore` |
| **Bias checks** | Pad a comment with polite filler (verbosity) or reverse the criteria (position): a good judge's scores don't move. | `judge.py`: `bias_shift` |
| **System-blind rating** | The rater never sees which system wrote a comment, so ratings can't favour "the agent". | `labeling/ratings.py`: `sample_items` |
| **Open coding → taxonomy** | Tag failures in your own words, then merge the codes into categories. A code-to-category map lets human and LLM tags meet. | `labeling/failure_tags.py`, `configs/failures/taxonomy.yaml` |
| **Validated automation** | An LLM tagger is trusted only after per-category κ against a person. | `eval/failure_tagger.py`: `tag_agreement` |
| **Testing a UI without a browser** | Streamlit's AppTest drives real pages; configuration comes from the environment because AppTest doesn't set `sys.argv`. | `tests/test_labeling_app.py` |

## 2. What we verified before coding (§14, 2026-09-30)

- **Streamlit 1.64.0** (PyPI, 2026-09-15; docs.streamlit.io):
  - it runs on Starlette/Uvicorn since 1.57;
  - `st.pills` and `st.segmented_control` (1.40), `shortcut=` on buttons (1.52), and `st.navigation` + `st.Page` for multipage apps are all available;
  - `st.feedback` has no 4-level option, so the 1-4 ratings use a segmented control;
  - `st.markdown` escapes HTML but *still renders Markdown*, so untrusted issue bodies are shown with `st.text`;
  - usage statistics are on by default, so we turn them off;
  - AppTest has `from_file`, `click().run()` and `segmented_control`/`pills` accessors.
- **GPT-6 Luna on OpenRouter:** it supports structured outputs and rejects `temperature` (checked in M4's endpoint audit), so the judge sends none.

## 3. Results (dev; labels by a model annotator at the owner's request, ADR-0035)

**Label noise, silver vs. adjudicated** (`reports/gold/dev.md`, 97 usable issues):

| task | κ | agreement | what it means |
|---|---|---|---|
| type label | 0.72 | 81% | Maintainers often label demonstrated crashes `type-bug`. |
| all labels, pooled per label | 0.84 | 98% | |
| duplicates | 1.00 | 100% | Every maintainer closure held up. |
| component | 0.90 | 93% | The derived component sometimes follows side files. |
| **needs-info** | **0.00** | 85% | Silver 15, gold 0: `pending` ≠ "needs info" in CPython. |

**Re-scored on the adjudicated labels** (`reports/results/dev-gold.md`; paired, agent minus baseline):
- **vs. TF-IDF:**
  - type labels **+0.11 [+0.03, +0.19]** (no evidence on silver);
  - duplicates **+0.34**;
  - components +0.08 [−0.02, +0.19] (significant on silver).
- **vs. single-shot LLM:** labels **+0.05 [+0.01, +0.10]**.

**Judge** (GPT-6 Luna, prompt v2 frozen; `reports/judge/`):

| criterion | judge-dev v1 → v2 QWK | judge-test QWK (once) | adjacent |
|---|---|---|---|
| correctness | 0.55 → 0.68 | **0.57** | 0.93 |
| actionability | 0.38 → 0.48 | **0.50** | 0.91 |
| tone | 0.10 → 0.14 | 0.17 (not validated) | 1.00 |

- Padding a comment with polite filler lowered its tone score by 1.8, so there's no verbosity bias.
- Reversing the criterion order moved scores by at most 0.3.

**Failure taxonomy v1** (`docs/FAILURE_TAXONOMY.md`):
- 60 failures were open-coded into 20 codes, then consolidated into 10 categories.
- The top three are topic/OS over-labeling (28), code-location confusion (24) and type-label errors (17): **label judgement, not retrieval**.
- The LLM tagger reproduces 6 of 10 categories at κ ≥ 0.6. It can't judge "repository guidance unused" or "ground-truth noise".

## 4. Pitfalls

1. **Anchoring.** Showing the silver label before asking for the gold one inflates their agreement. We ask blind first and prefill the final form from the blind answer, not from silver.
2. **High agreement with a low κ.** On rare classes (needs-info around 12%, duplicates around 4%), raw agreement is high even for a rater who always says "no". Report κ, and the base rates.
3. **κ can be undefined.** If both raters give one constant answer, chance agreement is 1. We return None rather than a misleading 0 or 1.
4. **Judge-test leakage.** Looking at judge-test agreement, then editing the prompt, turns judge-test into judge-dev. The guard refuses a second measurement per judge version.
5. **Markdown is not "safe text".** Escaping HTML still renders links and images from an attacker-written issue body. Use plain text.
6. **Frozen item sets.** Re-sampling the comments to rate after a new run would change what "judge agreement" means. The set is written once and refuses to be overwritten.
7. **A self-adjudicated blind pass is not a baseline.** The design claimed a "human baseline" from the blind pass. But the same annotator made the gold starting from their own blind answer, so it scored 0.96 against itself. Blind-vs-final measures the evidence's effect; a baseline needs an *independent* annotator. Corrected in ADR-0031.
8. **A κ of 0.00 can be the finding.** Needs-info didn't fail to agree by chance: adjudication showed the silver label measures something else (`pending` = "awaiting a decision").
9. **Vocabulary drift in annotations.** An annotator used `topic-sysconfig`, a real label outside the scored vocabulary. The import refused the file; the label was dropped and noted.
10. **Deep merge strikes configs.** `route: {provider: openai}` inherited base.yaml's `quantization: bf16`. The price guard refused the call, and a new test checks every config's route.
11. **Judges saturate.** Luna gave tone 4 almost always. Scale-use guidance helped correctness and actionability but not tone, so report tone as unvalidated instead of tuning on 54 items.

## 5. How an interviewer might probe this

- *"How do you know your labels are right?"* → We don't assume it. A blind-then-adjudicated gold set measures silver noise per task with κ, and headline numbers use gold.
- *"How do you trust an LLM judge?"* → Measured against a human on held-out items (QWK), checked for verbosity and position bias, and frozen and versioned. Any change means re-measuring.
- *"Why quadratic weights?"* → Rubric scores are ordered. A 3 vs. 4 disagreement is minor and a 1 vs. 4 is severe, and quadratic weights encode that.
- *"How did you build the failure taxonomy?"* → Bottom-up: open coding of real failures, consolidated into categories, with an LLM tagger validated against the reference codes before it scaled. Report which categories it can't reproduce.
- *"Your labels came from an LLM. Isn't that circular?"* → It's a stated limitation. Provenance is recorded per label and the claims are worded accordingly ("model-adjudicated"). The annotator is a different family from both the agent (Qwen) and the judge (GPT). A human spot-check of about 20 issues would bound the error.

## 6. Try it yourself (optional exercises)

1. **A bias check of your own.** Add a third variant to `build_messages`: put the comment *before* the issue. Does the judge's correctness score move on judge-dev?
2. **Krippendorff's α.** Implement α for interval data in `eval/agreement.py` and compare it with QWK on your ratings. When do they disagree?
3. **Human cost.** `gold-report` prints your median blind-pass time. Put it next to the agent's p50 latency and cost per issue in the results table.

## 7. Self-check questions

1. Two raters agree on 95% of issues about needs-info, which is "yes" on 5% of them. Why might κ be near 0?
2. Why is the final gold form prefilled with the person's blind answer rather than the silver label?
3. What goes wrong if you tweak the judge prompt after seeing judge-test agreement?
4. Why do human failure tags and LLM tags need a taxonomy file to be compared?
5. Why show issue bodies with `st.text` instead of `st.markdown`?

<details><summary>Answers</summary>

1. If both mostly say "no", chance agreement `p_e` is already about 0.9 or higher. Agreement barely above chance gives κ ≈ 0, even though the raw agreement is 95%.
2. Prefilling from silver invites clicking "accept". That anchors the gold on silver and inflates silver-vs-gold agreement, the quantity being measured.
3. judge-test stops being held out: the reported QWK is then optimistic, like tuning on the test split. The guard forces a new version and a new measurement.
4. People write open codes in their own words. The taxonomy maps codes to categories, so both sides are compared on the same category names.
5. Issue bodies are untrusted. Markdown would render attacker-controlled links and images, while plain text shows exactly what was written.

</details>
