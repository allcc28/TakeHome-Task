"""Offline smoke test of the agent loop.

Runs agent.run() end to end against a stubbed model and stubbed tools, so the
loop, the memory compaction, the failure paths and the trace writer can be
exercised without an API key or a network call. Not a unit test suite - it is
here to catch structural breakage before spending a real run on it.

    .venv/bin/python -m tests.offline_loop_test
"""
import os
import shutil
import sys
import tempfile
from types import SimpleNamespace

from google.genai import types

from src import agent, config, llm as llm_mod, tools as tool_mod
from src.trace import Trace


def model_turn(*parts):
    return SimpleNamespace(
        candidates=[SimpleNamespace(content=types.Content(role="model", parts=list(parts)))],
        usage_metadata=SimpleNamespace(prompt_token_count=100, candidates_token_count=20),
    )


def call(name, **args):
    return types.Part(function_call=types.FunctionCall(name=name, args=args))


def text(t):
    return types.Part(text=t)


class StubLLM:
    """Replays a scripted sequence of model turns."""

    def __init__(self, script, trace=None):
        self.script, self.i, self.trace = script, 0, trace

    def generate(self, contents, system_instruction, tools=None, max_retries=4):
        if self.i >= len(self.script):
            raise RuntimeError("stub script exhausted")
        turn = self.script[self.i]
        self.i += 1
        if isinstance(turn, Exception):
            raise turn
        if self.trace:
            self.trace.event("model_response", model="stub", latency_s=0.0, attempt=0)
        return turn


def scenario(label, script, tool_impls, max_steps=8, live_results=2):
    print(f"\n--- {label} ---")
    config.MAX_STEPS = max_steps
    config.MAX_LIVE_TOOL_RESULTS = live_results
    for name, fn in tool_impls.items():
        agent.TOOL_FNS[name] = fn

    trace = Trace(question="test", model="stub", search_provider="stub", base_dir=OUT)
    llm_mod.LLM = lambda trace=None: StubLLM(script, trace)
    fc = agent.run(trace, today="2026-09-01")
    trace.write_markdown()

    kinds = [e["kind"] for e in trace.events]
    print("events:", " ".join(kinds))
    print("status:", fc.status, "| notes:", fc.notes[:80])
    print("probs sum:", round(sum(fc.probabilities), 4),
          "| median:", fc.median_seats, "| P(maj):", fc.p_republican_majority)
    assert abs(sum(fc.probabilities) - 1.0) < 1e-6, "probabilities must sum to 1"
    assert os.path.exists(os.path.join(trace.dir, "trace.jsonl"))
    return trace, fc, kinds


ok_search = lambda **kw: {"ok": True, "provider": "stub", "query": kw.get("query", ""),
                          "results": [{"title": "t", "url": "https://example.org/a", "snippet": "s"}]}
ok_fetch = lambda **kw: {"ok": True, "url": kw.get("url", ""), "chars": 9000,
                         "truncated": True, "text": "x" * 9000}
bad_fetch = lambda **kw: {"ok": False, "error": "HTTP 503 for " + kw.get("url", "")}

GOOD_PROBS = [0.04, 0.09, 0.14, 0.18, 0.22, 0.18, 0.11, 0.04]


OUT = os.path.join(tempfile.gettempdir(), "forecast-agent-offline-runs")


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT, exist_ok=True)
    # 1. Happy path with a tool failure, a repeated call, and enough fetches to
    #    force memory compaction.
    _, fc, kinds = scenario(
        "happy path + failed tool + repeat + compaction",
        [
            model_turn(text("I need the base rate."), call("web_search", query="midterm seat loss")),
            model_turn(call("fetch_page", url="https://example.org/a")),
            model_turn(call("fetch_page", url="https://example.org/b")),
            model_turn(call("fetch_page", url="https://example.org/b")),  # duplicate
            model_turn(call("fetch_page", url="https://example.org/c")),
            model_turn(call("submit_forecast", probabilities=GOOD_PROBS,
                            reasoning="anchored on historical midterm losses",
                            key_drivers=["approval"], source_urls=["https://example.org/a"])),
        ],
        {"web_search": ok_search, "fetch_page": ok_fetch},
    )
    assert "context_compacted" in kinds, "compaction should have fired"
    assert fc.status == "complete"

    # 2. Malformed probabilities are repaired, not accepted or crashed on.
    _, fc, kinds = scenario(
        "malformed probabilities",
        [model_turn(call("submit_forecast", probabilities=[5, 5, -1], reasoning="sloppy"))],
        {"web_search": ok_search, "fetch_page": ok_fetch},
    )
    assert "forecast_warnings" in kinds and fc.notes, "repairs must be recorded"

    # 3. Budget exhausted without a submission -> forced close.
    _, fc, kinds = scenario(
        "budget exhausted -> forced close",
        [model_turn(call("fetch_page", url="https://example.org/x")) for _ in range(3)]
        + [model_turn(call("submit_forecast", probabilities=GOOD_PROBS, reasoning="forced"))],
        {"web_search": ok_search, "fetch_page": bad_fetch},
        max_steps=3,
    )
    assert "budget_exhausted" in kinds and fc.status == "incomplete"

    # 4. Model dies outright -> placeholder, run still produces an artefact.
    _, fc, kinds = scenario(
        "model failure -> placeholder",
        [RuntimeError("model call failed after 4 attempts: 429")] * 2,
        {"web_search": ok_search, "fetch_page": ok_fetch},
    )
    assert fc.status == "incomplete" and "forecast_placeholder" in kinds

    print(f"\nall offline scenarios passed  (stub traces in {OUT}, not runs/)")


if __name__ == "__main__":
    sys.exit(main() or 0)
