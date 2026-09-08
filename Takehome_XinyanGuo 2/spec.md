# spec.md

What the system does, precisely enough that two people reading it build the
same thing and that you can run this repository and get the same behaviour.

Structure follows the arc of a small design doc: state the goal, fix the
scope, then output → interfaces → memory → failures → tracing, and finish with
the decisions that could reasonably have gone the other way.

---

## 0. Project goal

Build an LLM agent that produces a calibrated probability distribution for a
question about the future that has not yet resolved, and run it — with the
scaffolding around the model, not the prompt inside it, as the object of
interest. Two properties define success: the agent decides for itself what
information it needs and goes and gets it, and every run leaves a trace
complete enough to reconstruct how it got from evidence to an answer.

The question, fixed by the brief:

> How many seats will the Republican Party win in the U.S. House of
> Representatives in the 2026 midterm elections?

### 0.1 What exactly is being forecast

"How many seats" is less obvious than it looks, and the output format in §2
depends on pinning it down:

- **Universe:** all 435 voting seats of the U.S. House. Delegates and the
  Resident Commissioner are excluded.
- **Election:** the general election of **3 November 2026**, which seats the
  120th Congress in January 2027.
- **Counted as Republican:** a seat is Republican if the winner was on the
  ballot as the Republican nominee. Party *label at election*, not caucus
  behaviour — an independent who later caucuses with Republicans does not
  count, and a member who switches party after being seated does not change
  the number.
- **Resolution date:** the count as of the initial seating of the 120th
  Congress. Races undecided at that point (recounts, post-election runoffs,
  litigation) resolve to whoever is seated. Later vacancies do not change it.
- **Not counted:** special elections held before or after the general.

Stated so the forecast is falsifiable in principle, not because the agent
verifies them. Where these differ from a prediction market's own rules, the
market's rules govern that market's price and ours govern our number — a
discrepancy worth noting in a run rather than silently reconciling.

### 0.2 Non-goals

We are not producing a forecast anyone will trade on or be scored against. The
deliverable is the machinery, the reasoning it leaves behind, and the reading
that shaped it.

## 1. Scope

### 1.1 Requirements taken from the brief

These are not ours to trade away. Listed so a reader can check them off against
what is here.

| # | Requirement | Where it is met |
|---|---|---|
| R1 | An LLM agent that produces calibrated probabilities for the fixed question, and that has actually been run | §3, §10 |
| R2 | The agent works out for itself what information it needs and goes and gets it — no document set supplied | §3 |
| R3 | Every run traced and persisted: what it did, in what order, what came back, how it reached an answer | §7, `runs/` |
| R4 | The answer representation is a deliberate design decision, not a default | §2, §8 |
| R5 | A search tool, with the arrangement declared in the README | §4.4, README |
| R6 | Documentation as markdown, written the way you would write it for a coding agent | `README.md`, `CLAUDE.md`, `literature.md` |
| R7 | Spec covers interfaces, data contracts, failure handling, and what is in a first version and what is not | §4, §6, §1 |
| R8 | Claims traceable; model and version named; observed behaviour reported rather than expected | §9, §10, `literature.md` |
| R9 | Three to five pieces of prior work, each with what it changed | `literature.md` |
| R10 | Disclose which AI tools were used and for what | README |
| R11 | Roughly four to five hours; if cutting, cut scope before trace logging or the literature file | §1.3 |

### 1.2 Choices among the options

Where the brief left the decision open, this is what was picked. Each is argued
in §8.

| Decision | Choice | Alternative considered |
|---|---|---|
| Answer representation | PMF over 8 seat-count buckets | point estimate ± sd; full 0–435 PMF; quantiles |
| Runtime model | Gemini via Google AI Studio (free tier, no card) | Groq (OpenAI-compatible) |
| Search | Brave Search API free tier; Tavily and a keyless DuckDuckGo fallback also wired | scripted fetch of fixed pages |
| Agent shape | single tool-calling loop, hard step budget | plan-then-execute; multi-agent debate |
| Tool transport | direct HTTP inside the process | MCP server wrapping search |
| Interface | flag-driven CLI (`src/main.py`) | conversational NL layer; GUI |
| Memory | bounded working memory within a run; trace as durable store | long-term memory across runs |
| Coding agent | Claude Code (Opus 5), steered by `CLAUDE.md` and this spec | — |

### 1.3 Out of scope for v1

An MCP server wrapping the search tool; long-term memory across runs;
ensembling and repeated-sample aggregation; retrodiction scoring against past
midterms; programmatic extraction of Kalshi / Polymarket prices into the bucket
scheme; district-level modelling; any GUI.

Per R11, if time runs short the cut order is: scope from this list first,
then §2 refinements, and never the tracing in §7 or `literature.md`.

## 2. Output — how an answer is represented

The brief calls this out as a graded design decision, so it gets its own
section. The question is a count, not a binary, so the answer is a probability
mass function over contiguous, exhaustive, mutually exclusive seat buckets —
**not** a single number.

Every run ends with this object (`runs/<id>/result.json`):

```json
{
  "bucket_labels": ["<=189","190-199","200-209","210-217","218-225","226-235","236-245",">=246"],
  "probabilities": [0.04, 0.09, 0.14, 0.18, 0.22, 0.18, 0.11, 0.04],
  "median_seats": 221,
  "interval_80": [190, 245],
  "p_republican_majority": 0.55
}
```

Eight probabilities, one per bucket, summing to 1.0. The last three fields are
**derived** from the PMF, not independently asserted: `median_seats` is the
midpoint of the bucket where cumulative probability crosses 0.5, `interval_80`
the 10th–90th percentile bucket edges, and `p_republican_majority` the mass at
or above 218. In the example above the cumulative mass crosses 0.5 inside
`218-225`, so the median is 221, and 0.22 + 0.18 + 0.11 + 0.04 = 0.55 sits at
or above the majority line.

**Why the split at 217/218.** The majority threshold is the fact anyone
actually cares about. A bucket boundary exactly there makes `P(majority)` a sum
of bucket masses rather than an interpolation across a straddling bucket.

**Open decision.** These edges are chosen, not copied from a live market. The
"comparable to a market price" argument in §8 holds exactly only if the edges
match the bands Kalshi and Polymarket actually quote. Resolving it means either
hardcoding their bands or having the agent discover them at runtime. Recorded
here rather than papered over.

## 3. Architecture

Single agent, one tool-calling loop, hard step budget (`MAX_STEPS`, default 12).

```
main.py (CLI)
    |
    +-- Trace(run_id) ------------------> runs/<run_id>/{trace.jsonl, trace.md, result.json}
    |
    +-- agent.run()
          |  contents[]  <-- short-term memory, compacted (§5)
          |
          +-- web_search ------> Brave API | Tavily | DuckDuckGo (keyless)
          +-- fetch_page ------> requests + tag strip, truncated
          +-- submit_forecast -> terminal, ends the run
```

The model receives the question, a system prompt, the tool declarations, its
**position in the step budget** (the system instruction is rebuilt each step
with the model's current step and steps remaining — see §10.1), and the
current date. It is given **no documents**. Which searches to run, which pages
to read, and when to stop are its calls — that is the behaviour under test.

Termination is guaranteed three ways: the step budget, the terminal
`submit_forecast` tool, and the forced-close path (§6).

## 4. Interfaces and data contracts

### 4.1 Tools

Every tool returns a JSON-serialisable dict and **never raises**. A failure is
`{"ok": false, "error": "<message>"}`, handed back to the model as the function
result so it can see what happened and adapt.

```
web_search(query: str, max_results: int = 5)
  -> {ok: true, provider, query, results: [{title, url, snippet, age?}]}
   | {ok: false, error}

fetch_page(url: str)
  -> {ok: true, url, chars: int, truncated: bool, text: str}   # text <= 12000 chars
   | {ok: false, error}

submit_forecast(probabilities: float[8], reasoning: str,
                key_drivers?: str[], source_urls?: str[])
  -> terminal; ends the run
```

### 4.2 Forecast

`src/schemas.py`, serialised to `runs/<id>/result.json`: `bucket_labels`,
`probabilities`, `median_seats`, `interval_80`, `p_republican_majority`,
`reasoning`, `key_drivers`, `sources`, `status` (`complete` | `incomplete`),
`notes`.

### 4.3 Command line

`main()` in `src/main.py` is the entry point and the only user-facing
interface. Deliberately flag-driven rather than conversational: the question is
fixed by the brief, so an interactive natural-language layer would add surface
without producing evidence about the thing being tested.

```
python -m src.main [--today YYYY-MM-DD] [--max-steps N]
```

Writes the run directory, prints the `run_id` and the forecast as JSON.

Exit codes: `0` on a completed or degraded run, `2` on a configuration problem
found by preflight, non-zero otherwise on a crash. Preflight runs *before* the
run directory is created — a missing key is a config error and should not leave
a half-empty directory in `runs/`. It reports every problem at once rather than
one key per attempt.

### 4.4 External APIs

| Service | Used for | Auth |
|---|---|---|
| [Gemini API](https://ai.google.dev/gemini-api/docs) (Google AI Studio) | the runtime model, function calling | `GEMINI_API_KEY` |
| [Brave Search API](https://api-dashboard.search.brave.com/app/documentation) | `web_search` | `X-Subscription-Token: BRAVE_API_KEY` |

Free-tier limits shape §6: Brave is 1 query/second and 2000/month; Gemini's
free tier is rate- and quota-limited per model.

## 5. Short-term memory management

There is no memory across runs (§8). Within a run, the agent has two stores:

- **Working memory** — the `contents` list passed to the model each step. It
  holds the initial instruction, every model turn, and every tool result.
- **Durable memory** — `trace.jsonl`, written as events happen. Complete and
  never compacted.

Working memory would otherwise grow linearly in the number of steps, dominated
by fetched pages (up to 12k chars each; twelve of those is most of a run's
context). `ShortTermMemory` in `src/agent.py` bounds it:

- The `MAX_LIVE_TOOL_RESULTS` most recent tool results (default 6) stay in
  context verbatim.
- Older ones are replaced in place by a one-line stub naming what was there —
  `[compacted to save context] fetch_page(https://…) -> 9000 chars - full
  payload in trace.jsonl`.
- Model turns are never compacted. The agent's own reasoning is what carries
  a finding forward past the eviction of the page it came from, which is the
  intended behaviour: extract, then let the raw text go.
- Every eviction is a `context_compacted` trace event listing what was
  dropped, so you can always reconstruct what the model could still see at the
  moment it made a decision.

Two consequences worth stating. Nothing is lost — the full payload is already
in the trace. And a finding the model failed to write down before its source
was evicted is genuinely gone from working memory; if traces show that
happening, the fix is to raise `MAX_LIVE_TOOL_RESULTS` or to prompt for
note-taking, not to disable compaction.

An identical-call guard (§6) sits alongside this: repeating a call is the
other way a bounded context gets wasted.

## 6. Failure handling

| Failure | Behaviour |
|---|---|
| Brave 429 (free tier is 1 query/second) | Sleeps 1.2s, returns a recoverable error inviting a retry with a different query. Not run-ending. |
| Search/fetch HTTP error, timeout, DNS failure | Returned as `{ok: false, error}`; the model sees it and adapts. Logged as a `tool_result` with `ok: false`. |
| Non-text content type | Rejected before parsing, reported as an error string. |
| Identical repeated tool call | Short-circuited with `"identical call already made; vary it or move on"`. Stops the loop burning its budget re-running a failing call. **Known gap:** the comparison is on exact arguments, so a model that rephrases a query walks straight past it — see §10.1, where `gemini-3.5-flash` spent six steps on near-duplicate searches. A similarity check is the obvious fix and is not in v1. |
| Model 429 / 5xx / `RESOURCE_EXHAUSTED` | Retried up to 4 times, exponential backoff with jitter. This is the *expected* failure on a free tier, not an edge case. |
| Model returns no tool call | `no_tool_call` event; the loop nudges once and continues. |
| Model call fails after retries | `run_degraded` event, then forced close. |
| Step budget exhausted without a submission | `budget_exhausted` event, then forced close. |
| Forced close | One final call asking for the forecast now, given what it has. On success: `status = "incomplete"` with `notes` saying why. On failure: a uniform placeholder PMF, `status = "incomplete"` — the run still produces a readable artefact rather than nothing. |
| Malformed probabilities (wrong length, negative, not summing to 1) | Repaired in `validate_and_normalise`: padded/truncated, clamped at 0, renormalised. Every repair is a `forecast_warnings` event and is copied into `notes`. Never silent. |

The principle: a tool reports, it does not raise. Raising ends a run; reporting
gives the agent something to recover from, which is the behaviour being tested.

## 7. Tracing

`runs/<run_id>/trace.jsonl` — one JSON object per line, flushed on write, so a
crashed run still leaves a readable trace. Every event carries `ts`,
`elapsed_s`, `seq`, `kind`.

Event kinds: `run_start`, `step_start`, `model_response` (model, latency, token
counts), `model_error`, `model_text`, `no_tool_call`, `tool_call` (tool + full
args), `tool_result` (ok, error, full payload), `context_compacted`,
`forecast_warnings`, `forecast_submitted`, `budget_exhausted`, `run_degraded`,
`forced_close_failed`, `forecast_placeholder`, `run_end`.

`trace.md` renders the same events for a human, truncating payloads at 1500
chars. Lossy on purpose — the JSONL is the source of truth. `run_id` is
`<UTC timestamp>-<6 hex>`.

## 8. Design decisions: considered and rejected

**Output representation — why buckets, not a point estimate.**
*Point estimate + standard deviation:* rejected, assumes a symmetric unimodal
shape and cannot express "either a narrow Republican hold or a clear Democratic
majority, unlikely in between." *Full 0–435 PMF:* rejected, 436 numbers is more
precision than the evidence supports and more than a model emits coherently;
most of the mass is structurally zero. *Quantiles (10/25/50/75/90):* nearly
equivalent and reasonable; rejected in favour of buckets because buckets are
what the markets quote and a PMF is scorable with a multi-class Brier or log
score without interpolation.

**Loop shape — why one agent.**
*Plan-then-execute pipeline* (fixed retrieve → summarise → forecast): rejected,
a fixed pipeline is *us* deciding what information matters, which the brief
identifies as not answering the question asked. *Multi-agent debate or persona
ensemble:* rejected on time budget, and because with one run per configuration
there is no way to show it helped. First thing to add if calibration proves to
be the weak point. *SDK automatic function calling:* rejected, it hides the
call/result boundary, which is exactly what has to be traced.

**MCP server for search.** Rejected for v1. It is the better long-run shape for
a swappable tool surface, but it adds a subprocess, a transport and a new class
of failure between the repo and a working run, against a four-hour budget where
the brief is explicit that something which runs and handles a failed tool call
beats an elaborate architecture that never ran. Revisit once a full run works
end to end.

**Long-term memory across runs.** Rejected, and not only on time. If runs are
later used as evidence about calibration — N runs, look at the spread — shared
memory destroys the independence that makes the spread mean anything. The
per-run trace already gives durability; what was missing was a bound on working
memory, which is §5.

**Natural-language CLI.** Rejected. The question is fixed by the brief; a
conversational layer adds interface surface and no evidence.

## 9. Reproducibility

`temperature = 0.3`. Runs are **not** bit-reproducible: the agent reads a live
web whose content changes, and the model is not deterministic. The trace is
what makes a run auditable — every input the model saw is in it.

Model: **`gemini-3.7-flash`**, set as `GEMINI_MODEL` in `.env` and recorded in
`result.json` and the `run_start` event of every run.

The spec originally named `gemini-2.5-flash`. The API refused it — *"no longer
available to new users"* — so the model in use was chosen by listing what the
key could actually reach and probing the candidates for function-calling
support. Recorded here because it is the kind of detail that silently
invalidates a reproduction attempt.

**Rate limits shape the run, and are not incidental.** The key is on the Google
AI Studio *free tier*: 5 requests per minute per model
(`GenerateRequestsPerMinutePerProjectPerModel-FreeTier`) and 20 requests per
day per model (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`). A consumer
Gemini subscription does not change this — the API's paid tier comes from
enabling billing on the Google Cloud project behind the key, which is separate
from an app subscription. Three mitigations, all in `src/llm.py`: requests are
paced at `MIN_REQUEST_INTERVAL` (default 13s); a 429 is retried after the delay
the API itself asks for, parsed from the error body
(`retry_delay_from`), rather than after a blind exponential backoff that would
never clear a 60-second window; and a *daily* quota error is treated as
non-retryable (`is_daily_quota`), since waiting on it inside one run is pure
loss — it will not clear before the run ends. An 8-step run takes roughly four
minutes.

## 10. Observed behaviour

Nine runs, 1–3 September 2026, all in `runs/`, including the failed ones.
Regenerate this table with `.venv/bin/python -m tests.summarise_runs`.

| run | model | steps | searches | fetches | tool fails | model errors | compactions | secs | outcome |
|---|---|---|---|---|---|---|---|---|---|
| `…266758` | gemini-3.7-flash | 5 | 4 | 0 | 0 | 8 | 0 | 39 | placeholder — per-minute quota |
| `…5fa5dc` | gemini-3.7-flash | 8 | 7 | 1 | 1 | 5 | 2 | 260 | forecast, forced close |
| `…a69f7a` | gemini-3.7-flash | 3 | 2 | 0 | 0 | 14 | 0 | 615 | placeholder — daily quota |
| `…50ac95` | gemini-3.5-flash | 8 | 7 | 1 | 0 | 0 | 2 | 145 | forecast, forced close |
| `…0fe407` | gemini-3.1-flash-lite | 8 | 7 | 1 | 2 | 0 | 2 | 113 | forecast, forced close |
| `…0479ce` | gemini-3.5-flash | 10 | 7 | 2 | 0 | 2 | 3 | 145 | placeholder — daily quota at step 10 |
| `…03e252` | gemini-3.7-flash | **5/16** | 4 | 0 | 0 | 0 | 0 | 86 | **forecast, self-terminated** |
| `…c72c68` | gemini-3.5-flash | 16/16 | 13 | 3 | 0 | 0 | 10 | 281 | forecast, forced close |
| `…88139b` | gemini-3.7-flash | **4/8** | 3 | 0 | 0 | 0 | 0 | 56 | **forecast, self-terminated** |

The last three are the stopping experiment (§10.1) — `…03e252` and `…c72c68`
at an extended 16-step budget to see whether the agent would stop before
running out of room, `…88139b` at the ordinary default budget (8) as a plain
run rather than a stretched diagnostic. Six runs produced a real distribution;
three degraded to the uniform placeholder. All nine terminated and left a
complete trace.

### 10.1 The stopping experiment

The first six runs all spent their entire step budget and were force-closed,
so it was not possible to tell whether the agent would not stop or whether
eight steps was simply too few. The cause turned out to be a defect in the
prompt: the model was told once, in the static system instruction, that it had
`N` steps, and then asked to stop when "running low" — **a condition it was
never given the information to evaluate.** The step counter existed only in the
Python loop.

Two changes (`src/agent.py`):

1. The system instruction is **rebuilt each step** with the model's position —
   *"You are on step 4 of 16. 13 steps remain, including this one."* — plus an
   explicit warning inside the last quarter of the budget. Regenerating the
   instruction is cheaper than appending position markers to the conversation
   and cannot go stale.
2. The stopping rule was made operational. It was *"keep going until extra
   searching stops changing your view"*, which has no test the model can run.
   It is now: *"Before each search, name the bucket whose probability you expect
   it to move. If you cannot name one, you already have enough — submit."*

Three runs since the fix, two budgets:

| run | model | budget | steps used | outcome |
|---|---|---|---|---|
| `…03e252` | `gemini-3.7-flash` | 16 | **5** | submitted on its own — `status: complete` |
| `…c72c68` | `gemini-3.5-flash` | 16 | 16 | still force-closed |
| `…88139b` | `gemini-3.7-flash` | 8 (default) | **4** | submitted on its own — `status: complete` |

The answer is **model-dependent**. Given a stopping rule it can actually
evaluate, `gemini-3.7-flash` has now self-terminated on **both** runs since the
fix — once well inside a stretched 16-step budget, once at exactly half of the
ordinary default budget on a plain run with no extended budget to make stopping
easy. Both used *fewer* steps than the same model had used under the old
prompt (5 and 4, versus 8), and both are the only two `status: complete` runs
in the project.

`gemini-3.5-flash` did not stop, and the trace shows why, which was not what
was expected. It is not refusing to stop; **it gets stuck verifying a fact.**
Steps 2 through 7 of `…c72c68` are six consecutive near-duplicate searches all
trying to pin down the exact 2024 seat split:

```
s2  "119th United States Congress" Wikipedia seat count OR "2024 United States Hou…
s3  "2024 United States House of Representatives elections" "Republicans" "Democra…
s4  "2024 United States House of Representatives elections" "seats" "220" OR "221"…
s5  "2024 United States House of Representatives elections" "220" "215"
s6  "2024 United States House of Representatives elections" "seats" site:en.wikipe…
s7  "2024 United States House of Representatives elections" "220" OR "221" OR "222…
```

The identical-call guard (§6) did not fire because these are *similar*, not
identical. That is a real gap: the guard compares exact arguments, and a model
that rephrases its way around it burns the budget just as effectively. A
near-duplicate check — same tool, high query overlap, within the last few calls
— is the obvious next fix and is not in v1.

**What this does and does not show.** Two self-terminated runs from one model
is stronger than the one this section originally reported, and the fact that
`…88139b` stopped at half the *default* budget — not a stretched one built to
make stopping easy — is the more realistic evidence of the two. It is still
two runs, not a reliability claim: whether `gemini-3.7-flash` stops
consistently across many runs, and at what budget `gemini-3.5-flash` would
stop if it had one, are both untested. What is no longer open is the original
question — the agent *can* decide it has enough evidence and submit before
running out of room, once the stopping rule is something it can evaluate.

### What the agent did

The search sequence was similar across models and was not prompted in this
order. `gemini-3.5-flash` opened with **"who is the president of the united
states in 2026"** — establishing a fact its training cannot supply before
reasoning about a midterm penalty that depends on it. It then fetched the 2024
House results for a baseline, then the generic ballot, then forecaster
consensus. `gemini-3.7-flash` skipped straight to the generic ballot and
markets. This is the behaviour R2 asks for, and it was not scripted.

### The six distributions

| bucket | `5fa5dc` 3.7 | `50ac95` 3.5 | `0fe407` lite | `03e252` 3.7 | `c72c68` 3.5 | `88139b` 3.7 | range |
|---|---|---|---|---|---|---|---|
| `<=189` | 0.100 | 0.030 | 0.050 | 0.070 | 0.100 | 0.140 | 0.110 |
| `190-199` | 0.280 | 0.150 | 0.100 | 0.210 | 0.230 | 0.250 | 0.180 |
| `200-209` | 0.330 | 0.350 | 0.200 | 0.360 | 0.350 | 0.280 | 0.160 |
| `210-217` | 0.130 | 0.300 | 0.300 | 0.240 | 0.200 | 0.180 | 0.170 |
| `218-225` | 0.100 | 0.120 | 0.200 | 0.080 | 0.100 | 0.110 | 0.120 |
| `226-235` | 0.040 | 0.040 | 0.100 | 0.030 | 0.015 | 0.030 | 0.085 |
| `236-245` | 0.015 | 0.010 | 0.030 | 0.007 | 0.004 | 0.008 | 0.026 |
| `>=246` | 0.005 | 0.000 | 0.020 | 0.003 | 0.001 | 0.002 | 0.020 |
| **median** | 204 | 204 | 213 | 204 | 204 | 204 | 9 seats |
| **P(majority)** | 0.16 | 0.17 | 0.35 | 0.12 | 0.12 | 0.15 | **0.23** |

All six cite the same evidence — a D+6.6 generic ballot, the 220-215 Republican
baseline, the historical first-midterm penalty — and all six put most mass
below 218. `p_republican_majority` still ranges 0.12 to 0.35 across models.
Within `gemini-3.7-flash` specifically, the three runs (`5fa5dc`, `03e252`,
`88139b`) land at 0.16, 0.12, 0.15 — tighter, but still three points on the
same model, not a proper calibration sample.

The **0.23 spread on the headline number** is the most important row in the
table: a single run's third decimal place means nothing. These are different
models rather than repeated samples from one, so this is mostly cross-model
disagreement, not a within-model calibration estimate. The proper experiment —
N runs, one model, temperature > 0 — was not affordable under the 20-request
daily quota.

### Failures, and what they cost

- **Free-tier quota is the binding constraint**, in two forms: 5 requests per
  minute and **20 per day, per model**. Runs `…266758`, `…a69f7a` and `…0479ce`
  died on it. Switching model buys a fresh daily budget, which is part of why
  the table has three models in it — an artefact of the constraint, not a
  designed experiment.
- **Blind exponential backoff was wrong.** `…266758` retried at 1/2/4/8s
  against a quota asking for 59s. Fixed by parsing the API's own `retryDelay`.
- **Waiting on a daily quota is pure loss.** `…a69f7a` spent 615 seconds — ten
  minutes — retrying a quota that resets tomorrow. `is_daily_quota()` now marks
  those non-retryable.
- **Kalshi returned HTTP 429 to `fetch_page`** (bot protection). The agent
  found the seat-count market and could not read it, so market prices entered
  only through search snippets. This weakens the market-comparability argument
  in §2 and is the strongest reason to revisit the bucket edges.
- **`gemini-3.1-flash-lite` returned no `source_urls`** despite the tool schema
  asking for them, and had 2 tool failures to the others' 0–1. Cheaper model,
  worse instruction-following.
- **Near-duplicate searches are not caught** — see §10.1. `…c72c68` spent six
  steps on rephrased variants of the same query.
- **Compaction fired in six of the nine runs**, 2–10 evictions, all
  `fetch_page` results and stale searches. No run showed the model asking for
  something it had already been given and lost.

### What was not established

- **Whether stopping is reliable at scale.** §10.1 settled the original
  question — the agent will stop, given a rule it can evaluate — but on three
  runs across two models. Whether `gemini-3.7-flash` stops consistently, and at
  what budget `gemini-3.5-flash` would, are both untested.
- **Calibration.** Nothing here measures it. The question does not resolve
  until November 2026, and no retrodiction harness was built.
- **Whether the numbers are any good.** Six runs agreeing that Republicans
  probably lose the House is agreement with the prediction markets the agent
  read, which is not independent evidence.

### Verified without a model key

- Tool layer returns structured errors, not exceptions, for HTTP 500, DNS
  failure, and a missing Brave key; the keyless DuckDuckGo provider parses.
- `fetch_page` extracted 4,928 chars from a live 270toWin page.
- `validate_and_normalise` repairs wrong-length and unnormalised vectors,
  recording a warning for each.
- The full loop passes four offline scenarios against a stubbed model
  (`tests/offline_loop_test.py`): happy path with compaction and the
  identical-call guard; malformed probabilities repaired; budget exhaustion into
  forced close; total model failure into a placeholder — with a complete trace
  in every case. This exercises the plumbing, not the forecasting.
