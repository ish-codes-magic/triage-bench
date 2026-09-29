# M5: Gold labels, a calibrated judge, and a failure taxonomy

**What M5 built:** the human side of evaluation.
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

## 3. Results

*Pending the owner's labeling sessions (docs/LABELING_GUIDE.md):*
- silver-vs-gold κ per task (`triagelab gold-report`);
- the gold results table with the human baseline (`triagelab results --labels gold`);
- judge QWK on judge-dev, then once on judge-test (`triagelab judge calibrate`);
- taxonomy v1 and tagger agreement (`triagelab failures validate`).

## 4. Pitfalls

1. **Anchoring.** Showing the silver label before asking for the gold one inflates their agreement. We ask blind first and prefill the final form from the blind answer, not from silver.
2. **High agreement with a low κ.** On rare classes (needs-info around 12%, duplicates around 4%), raw agreement is high even for a rater who always says "no". Report κ, and the base rates.
3. **κ can be undefined.** If both raters give one constant answer, chance agreement is 1. We return None rather than a misleading 0 or 1.
4. **Judge-test leakage.** Looking at judge-test agreement, then editing the prompt, turns judge-test into judge-dev. The guard refuses a second measurement per judge version.
5. **Markdown is not "safe text".** Escaping HTML still renders links and images from an attacker-written issue body. Use plain text.
6. **Frozen item sets.** Re-sampling the comments to rate after a new run would change what "judge agreement" means. The set is written once and refuses to be overwritten.

## 5. How an interviewer might probe this

- *"How do you know your labels are right?"* → We don't assume it. A blind-then-adjudicated gold set measures silver noise per task with κ, and headline numbers use gold.
- *"How do you trust an LLM judge?"* → Measured against a human on held-out items (QWK), checked for verbosity and position bias, and frozen and versioned. Any change means re-measuring.
- *"Why quadratic weights?"* → Rubric scores are ordered. A 3 vs. 4 disagreement is minor and a 1 vs. 4 is severe, and quadratic weights encode that.
- *"How did you build the failure taxonomy?"* → Bottom-up: open coding of real failures, consolidated into categories, with an LLM tagger validated against the human codes before it scaled.

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
