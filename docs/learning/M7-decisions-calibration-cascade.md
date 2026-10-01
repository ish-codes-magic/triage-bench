# M7: Typed decisions, calibration, and a cascade

**What M7 built:**
- A decision layer: single questions (the issue's type label, its component) answered by interchangeable backends, each with a confidence.
- A hand-written calibration toolkit:
  - reliability diagrams;
  - ECE with equal-width and equal-mass bins;
  - Brier score;
  - risk–coverage curves and AURC;
  - slices.
- A cascade, at issue and decision level, evaluated offline from stored runs.

**Why it matters:**
- An LLM system is only as cheap as the share of work it can hand to something cheaper, and only as safe as its ability to know when *not* to.
- That's a question about **confidence**, not accuracy. Calibration makes "how much should I trust this answer?" measurable.

`jev_access: no` (owner, 2026-10-01), so the backends are an LLM with two confidence sources and a classifier. Jev would be one more implementation of `DecisionBackend`.

```
issue ─► decision backend ──(answer, confidence)──┐
          LLM verbalized | LLM logprobs | classifier│
                                                    ├─ conf >= τ ─► keep the cheap answer
cheap tier (stuffed agent) ─(full triage + conf.)───┘
                                                    └─ conf <  τ ─► escalate to the full agent
reports: triagelab calibration reports/calibration/e6.yaml   (E6)
         triagelab cascade     reports/cascade/e7.yaml       (E7, H3)
```

---

## 1. Concepts, and where they live

| Concept | What to take away | Code |
|---|---|---|
| **Typed decision** | One question, a typed answer (an option, yes/no, a number) and a confidence; no prose. It's the unit a cascade can gate. | `decisions/base.py`: `Decision`, `DecisionBackend` |
| **Verbalized confidence** | The model states a probability in its JSON answer. It's cheap to get, and here it's nearly always "0.98": no information about *which* answers are wrong. | `decisions/llm.py`: `_choose_verbalized` |
| **Logprob confidence** | Letter the options, read the first token's distribution, pool variants (" B", "b"), renormalise over the options. Thinking must be off so the answer *is* the first token. | `llm.py`: `letter_distribution`, `_choose_logprobs` |
| **A classifier as a backend** | Logistic regression on frozen embeddings of the same text, one head per question, free per call. A single-class head becomes a constant answer instead of an error. | `decisions/classifier.py`: `fit_head`, `ClassifierBackend` |
| **Reliability diagram / ECE** | Bin answers by confidence and compare each bin's accuracy with its mean confidence. Equal-mass bins avoid hiding mass in a few dense bins. | `eval/calibration.py`: `reliability_bins`, `ece` |
| **Brier score** | Mean squared gap between confidence and outcome. It rewards calibration *and* discrimination, so a constant 0.8 can have a low ECE but a poor Brier. | `calibration.py`: `brier` |
| **Risk–coverage / AURC** | Keep only the most confident X% of answers: how accurate are they? This is what a cascade actually exploits. Ties are kept together. | `calibration.py`: `risk_coverage`, `aurc` |
| **Slices** | Calibration breaks first on unusual inputs: short issues, log dumps, non-English text. | `eval/calibration_report.py`: `SLICES` |
| **Agreement gate** | A backend's confidence describes *its* answer. To gate someone else's answer, require agreement first; disagreement means escalate. | `decisions/cascade.py`: `agreement_signal` |
| **Cheapest-matching τ** | Choose the cheapest threshold whose metrics stay at the full system's level on dev, with ties to the larger τ. | `cascade.py`: `Thresholded.choose_tau` |
| **Cross-fitting** | Choose τ on half of dev, apply it to the other half, and swap. It's the honest estimate of a tuned threshold. | `cascade.py`: `Thresholded.cross_fitted` |
| **Offline cascade** | Stored predictions plus a threshold policy reproduce any cascade exactly, with no calls and no noise between tiers. | `cascade.py`: `Cascade`, `DecisionCascade` |

## 2. What we verified before coding (§14, 2026-10-01)

- **Logprobs on OpenRouter for Qwen3.5-9B:**
  - `logprobs` and `top_logprobs` are offered only by **Parasail (bf16)** and **Venice (fp8)**; DeepInfra offers neither.
  - A probe with thinking off returned the answer letter as the first token, with every option among the top 10.
  - At `temperature: 0` the returned logprobs are still the raw distribution (p(B) ≈ 0.90, not 1.0).
  - Parasail's shared pool was saturated (90% 429s), so E6 runs on Venice. Its distribution matched Parasail's to within about 0.1 nats per option (ADR-0042).
- **matplotlib 3.11.2** (PyPI, 2026-10-01): it ships type hints, but its plotting calls take untyped `**kwargs`, so strict pyright needs one check relaxed in `eval/figures.py` only.
- **Jev:** not verified, since there's no access. The protocol mirrors §11's interface.

## 3. Results (dev, adjudicated labels; silver alongside in the reports)

**E6: decision backends** ([report](../../reports/calibration/e6-gold.md)):

| type label | accuracy | mean conf. | ECE | AURC | $/1,000 issues |
|---|---|---|---|---|---|
| LLM, logprobs | **0.866** | 0.867 | **0.095** | **0.048** | $0.15 |
| LLM, verbalized | 0.814 | 0.976 | 0.162 | 0.120 | $0.16 |
| classifier | 0.753 | 0.731 | 0.131 | 0.066 | $0 |
| full agent (own conf.) | 0.794 | 0.891 | 0.103 | 0.151 | $6.73 |

- **Component:** the verbalized LLM matches the full agent (0.844 vs 0.844). The lettered format costs the logprob arm accuracy (0.729): the answer format changes the answer, not only the confidence.
- **H5:**
  - Verbalized confidences are overconfident and uninformative.
  - Logprob confidences rank answers best among the LLM signals.
  - Classifier probabilities track accuracy best on the silver labels they were trained on.
  - **On the type decision, every source is miscalibrated on short issues** (9 issues, ECE 0.27–0.44). On component the picture is mixed: the agent stays calibrated there (0.09).
  - No dev issue is non-English, so that slice can't be measured here.

**E7: cascade** ([report](../../reports/cascade/e7-gold.md)):
- **Issue level:** the stuffed agent alone is already within 0.01 of the full agent (labels 0.822 vs 0.831, components equal) at 1/6 of the cost. The self-confidence gate matches the full agent at τ = 0.70 (4% escalated, $1.38 vs $6.84 per 1,000 issues). Cross-fitted, it escalates 2% and lands near the cheap tier, so there's little left to escalate.
- **Decision level (H3):** a single logprob call alone beats the agent on the type label (0.866 vs 0.794, $0.15 vs $6.84 per 1,000; the Δ +0.072 [−0.031, +0.186] isn't significant), and a single verbalized call matches it on component. **H3 holds for these routine decisions:** agent-level accuracy at about 2% of the cost.

## 4. Common pitfalls

- **Gating on the wrong confidence.** A backend's confidence is about its own answer. Using it to accept another system's answer only makes sense when the two agree.
- **Reading ECE alone.** A backend that says 0.98 for everything can have a moderate ECE and still be useless for gating. Risk–coverage shows whether confidence *ranks* answers.
- **Tuning τ and reporting it on the same issues.** Report the cross-fitted row too; here it was noticeably less flattering than the in-sample one.
- **Format effects.** Switching from option names to letters changed component accuracy by 0.12. When comparing confidence methods, report accuracy too.
- **Provider capability gaps.** The logprob arm needs a provider that serves logprobs. Shared-pool capacity, not uptime, decided which one was usable.
- **Small slices.** 9 short issues can show a problem, but can't measure it.

## 5. How an interviewer might probe this

- "Why did the verbalized confidence fail?" RLHF-tuned models state high confidence; without sampling or logprobs there's little signal, which the risk–coverage curve exposes.
- "How would you choose τ in production?" Choose it on held-out data, with a target (cost, or accuracy parity), cross-fitted. Monitor the escalation rate and re-calibrate when it drifts.
- "Why not use the agent's own confidence to gate?" It's available and fairly calibrated, but by the time the agent has answered you've paid for it. A gate must be cheaper than what it saves.
- "Is a 9B model's logprob a probability?" It's a score from a model that wasn't trained to be calibrated for this task. Measure it, and recalibrate (e.g. Platt scaling, fitted on dev) if the cascade depends on its absolute value.
- "What would Jev change?" Only the backend: the protocol, calibration and cascade code stay as they are, and the same report answers the question.

## 6. Self-check questions

1. Why must thinking be off for the logprob confidence?
2. Two backends have the same ECE. How can one still be a much better gate?
3. Why does the agreement gate return 0 when the backend disagrees, instead of 1 minus its confidence?
4. The cascade's cross-fitted row escalated fewer issues than the in-sample row. Why is that plausible?
5. What does the decision-level result imply for the architecture?

---

**Answers**

1. The confidence is read from the first generated token's distribution. With thinking on, the first tokens are reasoning, and the answer letter's distribution is conditioned on text we don't control.
2. ECE averages calibration within bins. A gate needs *discrimination*: wrong answers must sit at lower confidence than right ones. AURC and the risk–coverage curve measure that; ECE doesn't.
3. Its confidence is about its own answer. 1 − c would be a probability that the backend is wrong, not that the cheap tier is right; disagreement is the evidence to act on.
4. The in-sample τ was chosen to match the full agent on all of dev, so it fits that half's quirks. Chosen on one half, τ often turned out lower (0.00 on one fold), because on that half the cheap tier already matched the agent.
5. Route the routine decisions (type, component) to a one-call backend, and spend the agent on what only it can do: duplicate search, the comment, hard cases. The cascade belongs at the decision level, not the issue level.
