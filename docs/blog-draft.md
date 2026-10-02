# I built an issue-triage agent to find out when it's worth it. Mostly, it isn't.

*Draft for the owner to edit. It is written in the first person; add a line on how the project was built (it was developed with an AI coding agent) if you want that stated.*

Most LLM projects I've seen answer the question "does it work?". I wanted to answer a less comfortable one: **when is each part worth its cost?** So I built a GitHub issue-triage system the slow way. The agent loop, the retrieval, the metrics and the evaluation are written from scratch instead of taken from a framework, five hypotheses were written down before any code, and every design choice was measured with confidence intervals.

Of the five hypotheses, two failed outright and two held only in part. That turned out to be the useful part.

## What I expected

The plan read like a conference talk. A new issue arrives. A cheap, typed decision model handles the routine calls: is this a bug or a feature request, which component does it belong to. When it isn't confident, it escalates to an LLM agent that searches past issues and the code through MCP tools, guided by an Agent Skill that encodes the repository's triage rules.

I expected each layer to earn its place:

- repository-specific skills would beat generic instructions;
- fetching context with tools would beat pasting it into the prompt;
- the cheap layer would match the agent on routine decisions at a fraction of the cost and latency;
- the harness would move to a new repository by swapping the skill;
- confidences would be usable for deciding when to escalate.

The data was CPython's issue tracker: 5,476 issues, each rebuilt exactly as it looked the second it was opened. The model was deliberately small, a 9-billion-parameter open model, so that any gain had to come from the system around it.

## The first surprise was the data

Before any model, the data told me two things I didn't expect.

**70% of CPython issue bodies name the pull request that fixed them.** A bot edits the issue after triage and appends a "Linked PRs" section. Any evaluation that uses today's issue text is giving the model the answer. I rebuilt every issue from GitHub's edit history and wrote a test that fails if a single post-creation field can change what the model sees.

**Labels aren't evidence of triage unless you know who applied them.** The repository I first picked looked 100% labelled. When I checked who had applied each label, 3% came from a human triager. The rest came from issue forms, which means "which form did the reporter click". I chose the repository by label provenance instead.

Later, adjudicating the labels showed that one of my five tasks didn't measure anything. CPython's `pending` label, which I had read as "needs more information", means "awaiting a decision". Agreement between the derived label and a careful reading was exactly zero. I dropped the task from the headline rather than report a number about nothing.

## A free classifier is a rude baseline

The first experiment set the tone. TF-IDF with logistic regression, which costs nothing, scored 0.71 on labels. The 9B model answering in one call scored 0.59. It was *significantly worse* than a bag of words.

Letting the model reason first brought it level. So the bar for everything I built afterwards was set by a bag-of-words classifier.

## What the agent did and didn't buy

The agent, with tools and a skill, eventually reached 0.83 on labels and was the only system that could find duplicates. Then the ablations took most of that story apart.

**Skills did nothing.** I compared no skill, a generic skill, a hand-written CPython skill and one generated automatically. None differed from no skill: +0.008, with an interval from −0.030 to +0.049. The reason was mundane. Left to itself, the small model loaded the skill on 1–2% of issues. Forcing it into context didn't help either. A model three times larger loaded it unprompted 72% of the time, so this is a finding about small models, not about skills.

**Tools didn't beat stuffing.** I replaced the tool-using agent with a prompt that simply has the eight most similar past issues pasted in. It matched the agent on every metric at one sixth of the cost. What helped was seeing labelled neighbours. Multi-step tool use added nothing measurable.

**Multi-agent didn't pay.** A planner with specialised subagents was cheaper and slightly worse.

What did work was unglamorous. Listing label strings exactly as they must be written was worth +0.475 on one metric. Making a field required in the output schema fixed a ranking metric. A mechanical guard against repeated tool calls cut cost by 9%. Dropping low-confidence topic labels added +0.056. Every instruction-based fix I tried failed. The lesson I'd carry to any small-model system: **change what the harness computes and filters, not what you ask the model to judge.**

## The cheap layer worked, with an asterisk

Asking one typed question in one call ("which type label?") matched or beat the full agent at about 2% of the cost. And the calibration result was clear: when the model *states* its confidence, it says 0.98 about everything, right or wrong. Confidence from token log-probabilities was both calibrated and useful.

So I assembled the final system from what the measurements supported: typed calls for the two routine decisions, the stuffed agent for the rest. On the development set it matched the full agent at a fifth of the cost. That was the configuration I froze.

## Then I ran the test set, once

I had kept 50 CPython issues untouched, and 50 from a second repository, `astral-sh/uv`, to test transfer. I wanted "we only looked once" to be checkable, so the configs, a hash of the code and the dataset were committed to git before the run, along with a written analysis plan. The run happened in CI behind a manual approval, and the tool refuses a second run.

It failed safely before it ran at all: my code hash sorted files differently on Windows and Linux, so CI decided the frozen code had changed and refused. Nothing had been scored. I fixed the sort, added a test that runs on both platforms, and re-froze.

Then the results:

- **Labels held up.** The cheap system scored 0.88 against the full agent's 0.80, at 21% of the cost.
- **Component routing didn't.** It had tied the agent on development data (0.84) and scored 0.73 on test. Routing that decision to a typed call was the one choice I had *selected* on the development set, from a tie. It was the one number that fell below its interval. That's the winner's curse, in a table.
- **Cheaper wasn't faster.** The cheap system was slower than the agent, because its base model often reasons until it hits the output limit.
- **Transfer was half true.** The harness ran on uv after I moved one hard-coded CPython sentence out of the shared prompt. But the ranking didn't carry over: on uv the full agent led, and my cheap system was no better than a single model call.

One number was too good: a perfect 50 out of 50 on CPython's type label. I treated it as a suspected leak and wrote an audit that re-derives, from the run's traces, everything the model was allowed to see: 6,478 past issues, none from the future. The explanation was an easier sample. A perfect score on 50 items supports "above 0.94", not 1.00.

The most useful finding came from uv. Its maintainers mostly intervene to re-label a bug report as a question. My systems got the type right on 31 or 32 of the 34 issues nobody re-labelled, and on 5 to 7 of the 16 a maintainer had triaged. They were agreeing with the reporter, and failing exactly where triage adds value.

Running each system three times added one more correction. The full agent's type label was 77% accurate, but right in all three runs on only 67% of issues. The typed call gave the same answer 99% of the time.

## What I'd tell someone starting this

- **Start with the free baseline and the label audit.** They changed more conclusions than any model did.
- **Freeze before you look.** The one decision I tuned on development data is the one that didn't survive.
- **Report the interval, and say "inconclusive".** With 50 issues, most differences are.
- **Audit the result you like.** I checked the perfect score harder than any bad one.
- **Measure consistency.** Average accuracy hides what a user can rely on.

The system I ended up with is modest: two typed calls and a prompt with retrieved examples, for about $1.40 per thousand issues. The whole project cost $14.58 in model calls. What I have at the end is less a triage agent than a set of measurements about where one helps, and I trust those more than I would trust a demo.

*Everything is reproducible: three commands rebuild the headline tables from public data and committed predictions, with no API key.*
