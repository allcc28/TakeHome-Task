"""The agent loop.

Shape: a single tool-calling loop. The model is given the question, a tool
surface, and a step budget; it decides what to search for, what to read, and
when it knows enough. It ends the run by calling submit_forecast.

We deliberately do NOT hand it a document set - working out what information
it needs is the part of the task being tested.
"""
import json

from . import config, llm as llm_mod, tools as tool_mod
from .schemas import BUCKET_LABELS, Forecast, Source, derive_stats, validate_and_normalise

QUESTION = (
    "How many seats will the Republican Party win in the U.S. House of "
    "Representatives in the 2026 midterm elections?"
)

SYSTEM = f"""You are a forecasting agent. Today's date is provided in the user turn.

Your job is to produce a calibrated probability distribution for this question:
  {QUESTION}

The election is on 3 November 2026 and has not happened. There are 435 seats;
218 is the majority threshold. You must work out for yourself what evidence you
need and go and get it with the tools. You have not been given any documents.

Useful lines of evidence to consider gathering (not exhaustive, and you decide):
prediction market prices for House control and seat-count bands, generic ballot
polling, presidential approval, historical midterm losses for the president's
party, retirements and open seats, redistricting changes, and special-election
overperformance.

Method:
- Search first, then read the most informative pages.
- Before each search or fetch, name the bucket whose probability you expect it
  to move, and by roughly how much. If you cannot name one, you already have
  enough evidence: call submit_forecast instead of searching again.
- Anchor on a base rate (historical midterm seat swings) and update on current
  evidence. Say what you anchored on.
- Prefer sources that quote numbers. Note the date of anything you rely on.
- If a tool fails, read the error, and adapt: reformulate, try another source,
  or proceed without it. Do not repeat an identical failing call.
- Report what you actually found. If the evidence is thin, widen your
  distribution rather than inventing precision.

Finish by calling submit_forecast exactly once. Probabilities must be over these
buckets, in this order, and sum to 1.0:
  {BUCKET_LABELS}
{{position}}

Stopping is your decision, not the budget's. Submitting early with a wider
distribution is a better answer than spending every step and being forced to
submit at the end."""

TOOL_DECLS = [
    {
        "name": "web_search",
        "description": "Search the web. Returns titles, URLs and snippets.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query."},
                "max_results": {"type": "integer", "description": "1-10, default 5."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "fetch_page",
        "description": "Fetch a URL and return its text content, truncated.",
        "parameters": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    },
    {
        "name": "submit_forecast",
        "description": "Submit the final answer. Call this exactly once, last.",
        "parameters": {
            "type": "object",
            "properties": {
                "probabilities": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": f"{len(BUCKET_LABELS)} probabilities, one per bucket, in order, summing to 1.0.",
                },
                "reasoning": {
                    "type": "string",
                    "description": "How you got here: base rate anchored on, what moved you, and how much.",
                },
                "key_drivers": {"type": "array", "items": {"type": "string"}},
                "source_urls": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["probabilities", "reasoning"],
        },
    },
]

TOOL_FNS = {"web_search": tool_mod.web_search, "fetch_page": tool_mod.fetch_page}


def run(trace, today: str) -> Forecast:
    llm = llm_mod.LLM(trace=trace)
    def system_for(step):
        """Rebuilt each step so the model can see where it is.

        The stopping rule used to reference a step count the model was never
        shown - it was told 'you have N steps' once and then asked to stop when
        'running low', a condition it had no way to evaluate. Every run spent
        its whole budget. Regenerating the system instruction is cheaper than
        appending position markers to the conversation, and never goes stale.
        """
        left = config.MAX_STEPS - step
        pos = (f"You are on step {step + 1} of {config.MAX_STEPS}. "
               f"{left} step{'s remain' if left != 1 else ' remains'}, including this one.")
        if left <= max(2, config.MAX_STEPS // 4):
            pos += (" You are running low. Submit now unless you can name a "
                    "specific gap that one more call would close.")
        return SYSTEM.replace("{position}", pos)

    contents = [
        llm_mod.user_text(
            f"Today's date is {today}. Begin. Work out what you need to know, "
            f"gather it, then submit a forecast."
        )
    ]
    seen_calls = set()
    memory = ShortTermMemory(trace)
    system = system_for(0)

    for step in range(config.MAX_STEPS):
        trace.event("step_start", step=step, steps_left=config.MAX_STEPS - step)
        system = system_for(step)
        try:
            resp = llm.generate(contents, system, tools=TOOL_DECLS)
        except Exception as e:
            trace.event("run_degraded", reason=f"model call failed: {e}", step=step)
            return _forced_close(llm, contents, system, trace, f"model call failed: {e}")

        text, calls = llm_mod.split_parts(resp)
        if text:
            trace.event("model_text", step=step, text=text)
        if not calls:
            # No tool call and no submission: nudge once, then give up on the loop.
            trace.event("no_tool_call", step=step)
            contents.append(resp.candidates[0].content)
            contents.append(llm_mod.user_text(
                "You did not call a tool. Either call a tool or call submit_forecast now."
            ))
            continue

        contents.append(resp.candidates[0].content)

        for name, args in calls:
            trace.event("tool_call", step=step, tool=name, args=args)

            if name == "submit_forecast":
                fc = _build_forecast(args, trace)
                trace.event("forecast_submitted", forecast=fc.to_dict())
                return fc

            fn = TOOL_FNS.get(name)
            if fn is None:
                result = {"ok": False, "error": f"unknown tool {name!r}"}
            else:
                key = (name, json.dumps(args, sort_keys=True, default=str))
                if key in seen_calls:
                    result = {"ok": False, "error": "identical call already made; vary it or move on"}
                else:
                    seen_calls.add(key)
                    result = fn(**args)

            trace.event(
                "tool_result",
                step=step,
                tool=name,
                ok=result.get("ok"),
                error=result.get("error"),
                result=result,
            )
            memory.add_tool_result(contents, name, args, result)
        memory.compact(contents, step)

    trace.event("budget_exhausted", max_steps=config.MAX_STEPS)
    return _forced_close(llm, contents, system, trace, "step budget exhausted")


class ShortTermMemory:
    """Working memory for a single run.

    The context is the agent's short-term memory and the trace is its durable
    one. Fetched pages are the only thing here big enough to matter, so rather
    than let them accumulate for the whole run we keep the N most recent tool
    results verbatim and replace older ones with a one-line stub naming what
    was there. Nothing is lost - the full payload is already in trace.jsonl -
    but the model stops re-reading a page it has already extracted from, and
    the context stays roughly flat in the number of steps instead of growing
    linearly with it.

    Evictions are traced, so you can always see what the model could still see
    at the point it made a decision.
    """

    def __init__(self, trace):
        self.trace = trace
        self.slots = []  # (index into contents, tool name, short description)
        self.compacted = set()  # indices already replaced by a stub

    def add_tool_result(self, contents, name, args, result):
        contents.append(llm_mod.function_result(name, result))
        self.slots.append((len(contents) - 1, name, _describe(name, args, result)))

    def compact(self, contents, step):
        keep = config.MAX_LIVE_TOOL_RESULTS
        if len(self.slots) <= keep:
            return
        evicted = []
        for idx, name, desc in self.slots[:-keep]:
            if idx in self.compacted:
                continue
            note = f"[compacted to save context] {desc} - full payload in trace.jsonl"
            contents[idx] = llm_mod.stub_function_result(name, note)
            self.compacted.add(idx)
            evicted.append(desc)
        if evicted:
            self.trace.event(
                "context_compacted", step=step, evicted=evicted, kept=keep
            )


def _describe(name, args, result):
    if not result.get("ok"):
        return f"{name}({_arg_summary(args)}) failed: {result.get('error', '')[:120]}"
    if name == "fetch_page":
        return f"fetch_page({result.get('url', '')}) -> {result.get('chars', 0)} chars"
    if name == "web_search":
        n = len(result.get("results", []))
        return f"web_search({args.get('query', '')!r}) -> {n} results"
    return f"{name}({_arg_summary(args)})"


def _arg_summary(args):
    return ", ".join(f"{k}={str(v)[:60]!r}" for k, v in (args or {}).items())


def _forced_close(llm, contents, system, trace, reason: str) -> Forecast:
    """Last-ditch: ask for the forecast with no tools. If that fails, return
    an explicitly incomplete result rather than nothing."""
    try:
        contents = contents + [
            llm_mod.user_text(
                f"Stop researching ({reason}). Call submit_forecast now with your "
                f"best distribution given what you have."
            )
        ]
        resp = llm.generate(contents, system, tools=TOOL_DECLS)
        _, calls = llm_mod.split_parts(resp)
        for name, args in calls:
            if name == "submit_forecast":
                fc = _build_forecast(args, trace)
                fc.status = "incomplete"
                fc.notes = f"forced close: {reason}"
                trace.event("forecast_submitted", forced=True, forecast=fc.to_dict())
                return fc
    except Exception as e:
        trace.event("forced_close_failed", error=str(e))

    fc = Forecast(
        bucket_labels=BUCKET_LABELS,
        probabilities=[1.0 / len(BUCKET_LABELS)] * len(BUCKET_LABELS),
        status="incomplete",
        notes=f"no forecast produced ({reason}); uniform placeholder written so the run is still readable",
    )
    fc.__dict__.update(derive_stats(fc.probabilities))
    trace.event("forecast_placeholder", forecast=fc.to_dict())
    return fc


def _build_forecast(args: dict, trace) -> Forecast:
    probs, warnings = validate_and_normalise(list(args.get("probabilities", [])))
    if warnings:
        trace.event("forecast_warnings", warnings=warnings)
    fc = Forecast(
        bucket_labels=BUCKET_LABELS,
        probabilities=[round(p, 4) for p in probs],
        reasoning=args.get("reasoning", ""),
        key_drivers=list(args.get("key_drivers", []) or []),
        sources=[Source(url=u) for u in (args.get("source_urls", []) or [])],
        notes="; ".join(warnings),
    )
    fc.__dict__.update(derive_stats(probs))
    return fc
