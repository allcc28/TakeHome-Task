# CLAUDE.md

Instructions for Claude Code working in this repository. (the prompt inside the forecasting agent lives in
`src/agent.py`.)

## What this repo is

An LLM agent that forecasts a prediction-market question — how many US House
seats the Republican Party wins in the November 2026 midterms — as a
probability distribution, with every run traced to disk. Read `spec.md` before
changing anything; it is the contract.

## Ground rules

- **Do not hand the forecasting agent a document set.** It works out what it
  needs and fetches it. Pre-supplying context defeats the purpose of the
  exercise. If you find yourself adding a `sources.json`, stop.
- **Tools never raise.** They return `{"ok": false, "error": "..."}` so the
  model can see the failure and adapt. A tool that raises ends the run.
- **Never drop a trace event.** If you add a branch to the agent loop, add an
  event for it. `runs/*/trace.jsonl` is the primary artefact and is read more
  closely than the code.
- **No silent repair.** If you fix up malformed model output, record it as a
  warning in the trace and in `Forecast.notes`.
- **Every run must terminate.** Step budget, terminal tool, forced close. If
  you add a loop, say how it ends.
- **Working memory is bounded; the trace is not.** Tool results older than
  `MAX_LIVE_TOOL_RESULTS` are stubbed out of the context in place (`spec.md`
  §5). Never compact the trace, and never compact a model turn — the agent's
  own reasoning is what carries a finding past the eviction of its source.
- Keep provider-specific code in `src/llm.py` and `src/tools.py`. The agent
  loop should not import `google.genai`.

## Layout

```
src/config.py    env-backed settings
src/schemas.py   buckets, Forecast, probability validation, derived stats
src/trace.py     Trace: JSONL + markdown + result.json per run
src/llm.py       Gemini wrapper: retries, backoff, part splitting
src/tools.py     web_search (Brave), fetch_page — structured errors, no raising
src/agent.py     system prompt, tool declarations, ShortTermMemory, the loop
src/main.py      CLI entry, preflight config check
tests/           offline_loop_test.py  - stubbed-model smoke test, no key needed
                 summarise_runs.py     - one-table summary of everything in runs/
runs/            one directory per run; committed, not gitignored
```

## Conventions

- Python 3.13, stdlib + `google-genai`, `requests`, `python-dotenv`. Don't add
  dependencies without a reason worth defending out loud.
- Secrets come from `.env` only. Never commit a key; never print one.
- Comments explain *why a call was made*, not what the line does. This code
  gets walked through in an interview.

## Running

```bash
.venv/bin/python -m src.main --max-steps 8
```

Prefer a small `--max-steps` while iterating — free-tier quota is the binding
constraint, not wall-clock time.

## Checkpoint — work plan status

Work is grouped into stages sized to fit one working window. **Stop at the end
of a stage.** Do not roll into the next one without being asked — the exit
criterion is there so that stopping is clean and the next session can resume
from this file without re-deriving anything.

A dispatched agent updates this section as the last step of its task, in the
same change as the work.

**Current position: Stages 1-4 and 6 complete, plus a follow-up experiment on
agent self-termination (`spec.md` §10.1). Stage 5 (`literature.md`) is
outstanding and is the human's to do.**

| Stage | Goal | Status |
|---|---|---|
| 1 | Skeleton that runs | done |
| 2 | Documentation baseline | done |
| 3 | First live run | done — two runs, second produced a real forecast |
| 4 | Evidence from real runs | done — 6 runs, `spec.md` §10 written |
| 5 | Literature review | **outstanding — owner: human** |
| 6 | Final pass | done except what depends on Stage 5 |

---

### Stage 1 — Skeleton that runs · done

| # | Task | Where |
|---|---|---|
| T1 | Repo layout, deps, `.env.example` | root, `requirements.txt` |
| T2 | Buckets, `Forecast`, probability validation | `src/schemas.py` |
| T3 | Trace: JSONL + markdown + `result.json` | `src/trace.py` |
| T4 | Gemini wrapper: retries, backoff, part splitting | `src/llm.py` |
| T5 | `web_search` (Brave / Tavily / DuckDuckGo), `fetch_page` | `src/tools.py` |
| T6 | Agent loop, tool declarations, forced close | `src/agent.py` |
| T7 | Short-term memory compaction | `src/agent.py` |
| T8 | CLI entry point | `src/main.py` |

*Exit criterion (met):* every module imports, tool failure paths return
structured errors, memory compaction verified without a model key.

### Stage 2 — Documentation baseline · done

| # | Task | Where |
|---|---|---|
| T9 | `spec.md` — goal, scope, output, architecture, interfaces, memory, failures, tracing, decisions | `spec.md` |
| T10 | `README.md`, `CLAUDE.md` | root |

*Exit criterion (met):* a reader could rebuild the system from `spec.md` alone.
§10 is knowingly empty until Stage 4.

### Stage 3 — First live run · done

| # | Task | Status | Where |
|---|---|---|---|
| T11a | Preflight config check — clear message, exit 2, no orphan run dir | done | `src/main.py` |
| T11b | Offline loop smoke test against a stubbed model | done | `tests/offline_loop_test.py` |
| T11c | Keys in `.env`; two runs executed | done | `runs/` |
| T12 | Fix what broke on first contact with a live model | done | `src/llm.py`, `src/config.py` |

*Exit criterion:* one run completes and writes a `result.json` with
`status: complete`. A degraded run that terminates cleanly and is fully traced
also counts — say so rather than hiding it.

*Offline coverage (T11b):* four scenarios pass without a key — happy path with
compaction, malformed probabilities repaired, budget exhaustion into forced
close, and total model failure into a placeholder. Run it before any live run:
`.venv/bin/python -m tests.offline_loop_test`. Stub traces go to a temp dir,
never to `runs/`.

*Token note:* read `runs/<id>/trace.md`, not `trace.jsonl`. The markdown is
truncated at 1500 chars per field and is far cheaper; drop to the JSONL only
for a specific event.

*What first contact actually broke (all fixed, all in the traces):*


1. Free tier is **5 requests/minute per model**. Blind exponential backoff
   (1/2/4/8s) can never clear a 60s quota window, so run 1 exhausted its retries
   and degraded to a uniform placeholder. Fixed two ways: `MIN_REQUEST_INTERVAL`
   paces requests at 13s, and 429s now wait for the delay the API asks for,
   parsed out of the error body (`retry_delay_from`).
2. `gemini-3.7-flash` returned 503 "high demand" four times across run 2. Backoff
   handled it; no change needed.
3. My own error truncation (400 chars) was cutting off the quota details that
   diagnose a 429. Raised to 1200.

**PAUSE HERE.** Stage 3 took the project from "does not run" to "runs". Look at
`runs/20260901T232948Z-5fa5dc/trace.md` before spending anything on Stage 4.

### Stage 4 — Evidence from real runs · done

| # | Task | Status | Where |
|---|---|---|---|
| T13 | Nine runs across three models | done | `runs/` |
| T13a | `summarise_runs.py` — one-table view of every run | done | `tests/summarise_runs.py` |
| T14 | Fill `spec.md` §10 from what the traces show | done | `spec.md` |
| T15 | Open decisions recorded, not resolved — see below | done | `spec.md` §2 |
| T22 | Stopping experiment: step-position injection + testable stop rule | done | `src/agent.py`, `spec.md` §10.1 |

*Exit criterion:* §10 describes observed behaviour — steps used, searches made,
failures hit and recovered from, whether compaction fired, how much the
distribution moved between runs — with no sentence that was not read off a
trace.

*Quota shaped the evidence.* The free tier gives 20 requests/day **per model**,
so a third data point meant a third model. The result is cross-model spread
(P(majority) 0.16–0.35), not the within-model calibration check that was
wanted. Recorded as a limitation in `spec.md` §10 rather than presented as an
experiment.

### Stage 5 — Literature review · owner: human

| # | Task | Where |
|---|---|---|
| T16 | Read the sources; write the "what it changed" line for each | `literature.md` |

*Exit criterion:* three to five entries, each with an honest "what it changed",
and every entry that changed nothing deleted.


### Stage 6 — Final pass · done (except what depends on Stage 5)

| # | Task | Where |
|---|---|---|
| # | Task | Status | Where |
|---|---|---|---|
| T17 | README status and "what I would do next" | done | `README.md` |
| T18 | AI-tools disclosure | needs your read | `README.md` |
| T19 | Exact model string recorded | done | `spec.md` §9 |
| T20 | No key in any tracked file; `.env` gitignored | done | verified by grep |
| T21 | Literature citations verified against arXiv | done | `literature.md` |

*Exit criterion:* R1–R11 in `spec.md` §1.1 all tick off, or the gaps are stated
plainly in the README.

---

### Open decisions (not blocked, just undecided)

- **Bucket edges** (`spec.md` §2) — keep the chosen edges, hardcode the real
  Kalshi / Polymarket bands, or have the agent discover them at runtime.
- **Evidence hints in the system prompt** (`src/agent.py`) — the prompt lists
  generic ballot, approval, retirements, redistricting. Stripping it makes the
  agent genuinely unaided, which is closer to what the brief tests, at the cost
  of a possibly worse run.
- **Near-duplicate tool calls are not caught.** The guard compares exact
  arguments; `gemini-3.5-flash` spent six steps rephrasing the same search
  (`spec.md` §10.1). Same tool + high query overlap within the last few calls
  would fix it. Roughly thirty minutes, not done.
- **Section order in `spec.md`** — two proposed moves (memory later, observed
  behaviour before reproducibility) discussed and not applied.

### Dispatching work

Tasks are sized to hand to a single agent. Anything dispatched:

1. Reads `spec.md` first — it is the contract, not this file.
2. Touches only the files named in its row.
3. Updates its row and the stage status here, in the same change.
4. Never edits `runs/`.
5. Stays inside its stage. Finishing early is not licence to start the next one.

## Do not

- Reformat or restructure files you were not asked to touch.
- Delete or edit anything in `runs/` — traces are evidence, including the
  failed ones. A run that went wrong is more interesting than one that didn't.
- Widen scope beyond `spec.md` §1 without updating `spec.md` in the same change.
