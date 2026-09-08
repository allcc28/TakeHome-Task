# 2026 US House Seat-Count Forecasting Agent

An LLM agent that works out for itself what it needs to know about the
3 November 2026 US midterms, goes and gets it from the open web, and returns a
**probability distribution** over how many House seats the Republican Party
wins. Every run is traced to disk. Calibration itself is not measured — the
election hasn't happened yet — see `spec.md` §10.

> Question: *How many seats will the Republican Party win in the U.S. House of
> Representatives in the 2026 midterm elections?*

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env      # then put your key in it
.venv/bin/python -m src.main
```

Options: `--today YYYY-MM-DD` (date handed to the agent), `--max-steps N`.

Each run writes `runs/<run_id>/` containing `trace.jsonl` (append-only event
log, the primary artefact), `trace.md` (the same run for a human), and
`result.json` (the forecast).

## Keys

| What | Env var | Notes |
|---|---|---|
| Runtime model | `GEMINI_API_KEY`, `GEMINI_MODEL` | Gemini via Google AI Studio — free, no card. |
| Search | `SEARCH_PROVIDER`, `BRAVE_API_KEY` | Brave Search API — free tier, no card. |

**On the search tool:** the default provider is **Brave** (free tier: 1 query
per second, 2000 per month — the rate limit, not the monthly cap, is what you
hit in practice, so a 429 is reported back to the agent as a recoverable error
rather than killing the run). `SEARCH_PROVIDER=tavily` is also wired up.
`SEARCH_PROVIDER=duckduckgo` needs no key at all and scrapes the DuckDuckGo
HTML endpoint — that is the declared no-signup fallback, kept because it makes
the tool layer testable without any key, but it is brittle by construction: if
the markup changes it returns `ok: false` rather than silently returning
nothing.

## What it does

The agent gets three tools — `web_search`, `fetch_page`, `submit_forecast` —
a step budget, and no documents. It decides what evidence it needs (market
prices, generic ballot, approval, historical midterm base rates, retirements,
redistricting), gathers it, and ends the run by submitting a distribution over
eight seat-count buckets.

Working memory is bounded: the most recent tool results stay in context
verbatim and older ones are replaced by a stub pointing at the trace, so the
context stays roughly flat in the number of steps. Nothing is lost — the trace
is the durable memory, the context is the working one (`spec.md` §5).

See `spec.md` for the question definition, interfaces, data contracts and
failure handling, and `literature.md` for the reading that shaped it.

## Answer representation

Not a point estimate. The output is a PMF over contiguous seat buckets:

```
<=189 | 190-199 | 200-209 | 210-217 | 218-225 | 226-235 | 236-245 | >=246
```

split at the 218 majority line, so `P(Republican majority)` falls out exactly
rather than being interpolated. Buckets mirror how Kalshi and Polymarket quote
seat-count markets, which makes the output directly comparable to a market
price and scorable with a multi-class Brier or log score. Reasoning in
`spec.md`.

## AI tools used

This repository was written with **Claude Code (Opus 5)** as the coding agent:
the agent loop, tool layer, tracing and this documentation were scaffolded from
`CLAUDE.md` and `spec.md`, then reviewed and revised by hand. The design
decisions in `spec.md` §2–3 — the bucket representation, the single-loop
architecture, what was rejected — are mine; I can defend them.

The model the forecasting agent itself calls at runtime is **Gemini via Google
AI Studio**, which is a different thing from the editor and is the one that
matters for the exercise. Search is the **Brave Search API** free tier.

*(Review this paragraph before submitting — it should describe what you
actually did.)*

## Status / what I would do next

Nine runs, 1-3 September 2026, all in `runs/` including the three that failed.
Six produced a real distribution; all nine terminated and left a complete
trace. `spec.md` §10 has the numbers and the failures.

Across six runs and three models, median seats ranges 204-213 and
`P(Republican majority)` ranges **0.12 to 0.35**. That spread is the number I
would draw attention to, not any point estimate. Every run anchored on the
historical first-midterm penalty, updated on a D+6.6 generic ballot, and put
most mass below the 218 majority line.

**The finding I would lead with** (`spec.md` §10.1). The first six runs all
spent their whole step budget and were force-closed, which looked like an agent
that would not stop. It was a defect in my prompt: the model was told once that
it had `N` steps and then asked to stop when "running low" - a condition it was
never given the information to evaluate, because the step counter lived only in
the Python loop. After rebuilding the system instruction each step with the
model's actual position, and replacing the vague stopping rule with a testable
one, `gemini-3.7-flash` stopped on its own at **step 5 of 16**. A follow-up plain
run at the ordinary default budget (8 steps) stopped again, at step 4 - using
fewer steps both times than it had under the old prompt, and producing the
only two `status: complete` runs in the project.

`gemini-3.5-flash` still ran to 16, and the trace shows why: it is not refusing
to stop, it gets stuck verifying a fact, spending six consecutive steps on
near-duplicate searches for the 2024 seat split. The identical-call guard misses
those because they are similar rather than identical. That gap is documented,
not fixed.

**What I would do next**, in the order I would actually do it:

1. **Buy the calibration experiment the quota denied me.** Every run above is a
   different model, because the free tier gives 20 requests per day *per model*
   and switching models was the only way to get a third data point. The
   experiment I wanted is N runs of one model at temperature > 0, which
   measures within-model variance instead of cross-model disagreement. It needs
   a billed key and about an hour.
2. **A near-duplicate call guard.** The existing guard compares exact
   arguments, so a model that rephrases its query walks past it - six wasted
   steps in run `…c72c68`. Same tool plus high query overlap within the last
   few calls would have caught every one of them. Perhaps thirty minutes.
3. **Fix market access.** Kalshi returns HTTP 429 to a plain fetch, so the
   agent found the seat-count market and could not read it — market prices
   reached it only as search snippets. Their public API would give real bucket
   prices, which would also settle the open question in `spec.md` §2 about
   whether my bucket edges should be the market's edges.
4. **Retrodiction.** Point the same agent at 2018 or 2022 with a date cutoff
   before the election and score the PMF against the known outcome. It is the
   only honest way to say anything about calibration, and nothing in this
   repository currently measures it.
5. **Strip the evidence hints from the system prompt.** It currently names the
   generic ballot, approval, retirements and redistricting. One model opened by
   searching *"who is the president of the united states in 2026"* unprompted,
   which suggests the hints may be doing less work than I assumed — worth
   testing by removing them.
