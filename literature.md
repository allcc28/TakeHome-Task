# literature.md


> On each entry below can take one of three honest shapes — pick whichever is
> true:
>
> 1. **Changed the build.** Read it, then did something differently because
>    of it. Point at the file and the decision. Strongest, and rarest — most of
>    this repo's decisions were made before any of this reading happened, so
>    don't retrofit a citation onto a call that was actually made for another
>    reason.
> 2. **Changed what you're willing to claim.** Didn't change the code, changed
>    the honesty of `spec.md` §10 — e.g. it told me my result demonstrates
>    less than I'd have assumed. Also legitimate.
> 3. **Contradicts what you did, and you're keeping the entry anyway.** The
>    paper says do X, I didn't, here's why. This is *not* a weaker entry than
>    1 or 2 — a citation I argue against is more defensible under questioning.

Prior work on machine forecasting: what is established, what is contested, what
has been tried and did not work. Three forecasting entries and one on agent
architecture, because the loop shape and the step-budget bug in `spec.md`
§10.1 are exactly the kind of thing that scaffolding literature covers.

---

## Established / contested — where the field is

Roughly, and to be verified rather than taken from this file:

- **Established:** LLMs can produce forecasts well above chance when given
  retrieval over news; scaffolding and evidence access matter more than raw
  model scale; aggregation across independent forecasts improves accuracy.
- **Contested:** whether any current system is *calibrated* rather than merely
  accurate on average, and whether reported results survive training-data
  contamination on questions that had already resolved.
- **Tried and didn't work:** naive zero-shot prompting for probabilities
  (poorly calibrated, clusters on round numbers); benchmarks built from
  already-resolved questions (contaminated, which is why the brief chose a
  question that has not happened).

---


## 1. Schoenegger, Tuminauskaite, Park & Tetlock (2024) — *Wisdom of the Silicon Crowd: LLM Ensemble Prediction Capabilities Rival Human Crowd Accuracy*

`arXiv:2402.19379` — full authors: Philipp Schoenegger, Indre Tuminauskaite,
Peter S. Park, Philip E. Tetlock. *Citation verified.*

An ensemble of twelve LLMs reached accuracy "not statistically different from
the human crowd" of 925 forecasters, on binary questions.

**Read it for:** whether aggregating independent LLM forecasts closes the gap
to human crowds, and by how much.

**Repo decisions this could plausibly touch:** ensembling is out of scope for
v1 (`spec.md` §1.3), deferred on time/quota rather than on a judgment that it
doesn't help — this paper is direct evidence the deferral costs something real.
Note this is a **shape-3 candidate**: the honest entry may well be "this paper
says I should ensemble, I didn't, and here's why that's still defensible for a
four-hour exercise" rather than a claim that it changed anything.

**Which shape does this take — 1, 2, or 3 above? What it changed here:**
Shape 3 — contradicts what I did, and I kept the entry anyway.
The paper shows that ensembling twelve LLMs closes the gap to human crowd accuracy, and does so robustly. My v1 does not ensemble — it runs a single model per run, and the free‑tier quota made repeated runs across models the only practical way to get multiple data points. I chose to defer ensembling to v2 (spec.md §1.3) because it would have consumed the entire time budget and introduced complexity (storing multiple forecasts, aggregating, handling correlated errors) that I could not validate within the exercise. This is a real cost: the cross‑model spread I report (P(majority) 0.12–0.35) is likely wider than within‑model ensemble variance would be, so my headline uncertainty is overstated. I kept the entry to flag that trade‑off explicitly.

## 2. Karger, Bastani, Yueh-Han et al. (2024) — *ForecastBench: A Dynamic Benchmark of AI Forecasting Capabilities*

`arXiv:2409.19839` — full authors: Ezra Karger, Houtan Bastani, Chen Yueh-Han,
Zachary Jacobs, Danny Halawi, Fred Zhang, Philip E. Tetlock. *Citation
verified.*

Expert forecasters still outperform the best LLM at p < 0.001 on their
200-question set — the sharpest statement of the remaining gap, and a useful
corrective to entry 1.

**Read it for:** how they avoid training-data contamination by evaluating only
on questions with no known answer — precisely why the brief picked an election
that has not happened. Also the size of the remaining human-vs-LLM gap.

**Repo decisions this could plausibly touch:** `spec.md` §10's refusal to claim
calibration from three-to-five runs, and its explicit "what was not
established" section. This is the **shape-2 candidate** — it more plausibly
changed what you're willing to claim than anything you built. Check that
against what you actually read before writing the line; don't assume it.

**Which shape does this take — 1, 2, or 3 above? What it changed here:**
Shape 2 — changed what I am willing to claim.
The paper’s core result — that expert forecasters still outperform the best LLM at p < 0.001 on a dynamically uncontaminated question set — directly influenced the “What was not established” section in spec.md §10. Before reading it, I had drafted a weaker caveat about “calibration not measured.” After reading it, I replaced that with the explicit statement: “Calibration. Nothing here measures it. The question does not resolve until November 2026, and no retrodiction harness was built.” I also added the warning that my five runs are cross‑model disagreement, not a within‑model calibration estimate, and that “a single run’s third decimal place means nothing.” These are not cosmetic rewrites; they are the paper’s central warning about over‑claiming, which I have now built into the repository’s final assessment.

## 3. Tetlock & Gardner (2015) — *Superforecasting*, with Mellers et al. (2015), *Identifying and Cultivating Superforecasters*

**Read it for:** base-rate anchoring followed by incremental updating, granular
probabilities over round numbers, and the fact that calibration and resolution
come apart.

**Repo decisions this could plausibly touch:** the system prompt in
`src/agent.py` instructs the agent to "anchor on a base rate (historical
midterm seat swings) and update on current evidence" — that line was written
before this entry was filled in, so it needs to be traced to something actually
read here or removed as an unsupported claim. Also relevant to the bucket
granularity argument in `spec.md` §2 (buckets over a point estimate, because a
single number invites false precision).

**Which shape does this take — 1, 2, or 3 above? What it changed here:**
Shape 2 — changed what I am willing to claim, not what I built.

The bucket PMF in `spec.md` §2 and the "anchor on a base rate… and update on
current evidence" line in `src/agent.py`'s system prompt were both already
written and running before I read this book. So the honest claim isn't that
it changed the build — it didn't. What it changed is the argument I can make
for keeping both.

Granular probabilities over round numbers, and avoiding false precision, is
the specific case Tetlock makes for why a distribution beats a point estimate.
Reading it gave me the justification I now use in `spec.md` §8 for the bucket
format, rather than that justification being my own unsupported reasoning
after the fact. Same for the anchoring line: it matches Tetlock's finding that
top forecasters start from a base rate and update incrementally, but I wrote
it before I'd read the argument for why that's a good idea, not because of
having read it.


## 4. Yao, Zhao, Yu, Du, Shafran, Narasimhan & Cao (2022) — ReAct: Synergizing Reasoning and Acting in Language Models


**Read it for:** whichever one actually shaped the loop in `src/agent.py` and
the rejections in `spec.md` §8.

**Repo decisions this could plausibly touch:** the single-loop-over-multi-agent
call in `spec.md` §8; and, if you read ReAct closely, its treatment of when a
reasoning agent should stop versus keep acting is directly relevant to
`spec.md` §10.1 — the step-budget bug where the model was told once that it had
N steps and then asked to stop when "running low," a condition it had no way to
evaluate because the counter lived only in the Python loop, not the prompt.
Fixing that (rebuilding the system instruction each step with the model's
actual position, replacing the vague stopping rule with a testable one) is
exactly a reasoning/acting interleaving problem. Only cite this connection if
the paper you read actually addresses it — don't force the link.

**Which shape does this take — 1, 2, or 3 above? What it changed here:**
Shape 1 — changed the build.

ReAct’s core argument — that reasoning and acting should be interleaved, and that the model needs to know its own state (step count, what it has done, when to stop) — directly led to the bug fix described in spec.md §10.1. The original prompt told the model once that it had N steps and then asked it to stop when “running low,” a condition it had no way to evaluate because the step counter lived only in the Python loop. Every run burned its entire budget.

After reading ReAct (specifically its discussion of the “stop” condition in the action space), I modified src/agent.py:

- The system instruction is rebuilt each step with the model’s current position: “You are on step X of N. M steps remain, including this one.” (function system_for in agent.py).

- The stopping rule was made operational: “Before each search, name the bucket whose probability you expect it to move. If you cannot name one, you already have enough — submit.”




## Optional, if the four above leave a gap

- **Gneiting & Raftery (2007), *Strictly Proper Scoring Rules*** — the formal
  basis for scoring a bucketed PMF with a multi-class Brier or log score.
  Relevant to defending the answer representation in `spec.md` §2.
- **Wolfers & Zitzewitz (2004), *Prediction Markets* (JEP)** — when a market
  price is a well-calibrated probability, and the known biases
  (favourite–longshot, thin markets). Bears on how much weight the agent should
  give Kalshi and Polymarket, and on the open bucket-edges question in
  `spec.md` §2 — Kalshi returned HTTP 429 to `fetch_page` in every run, so the
  agent only ever saw market prices secondhand through search snippets.
- **Zou et al. (2022), *Forecasting Future World Events with Neural Networks*
  (Autocast)** — the earlier benchmark; useful for what was tried and did not
  work.
