"""Entry point:  python -m src.main"""
import argparse
import json
import sys
from datetime import date

from . import config
from .agent import QUESTION, run
from .trace import Trace


def preflight():
    """Check configuration before creating a run directory.

    A missing key is a config error, not a failed run - it should not leave a
    half-empty directory in runs/ behind. Reported as a list so you fix
    everything in one go rather than one key per attempt.
    """
    problems = []
    if not config.GEMINI_API_KEY:
        problems.append("GEMINI_API_KEY is empty - get one free at https://aistudio.google.com/apikey")
    if config.SEARCH_PROVIDER == "brave" and not config.BRAVE_API_KEY:
        problems.append("SEARCH_PROVIDER=brave but BRAVE_API_KEY is empty "
                        "(https://api-dashboard.search.brave.com), or set SEARCH_PROVIDER=duckduckgo")
    if config.SEARCH_PROVIDER == "tavily" and not config.TAVILY_API_KEY:
        problems.append("SEARCH_PROVIDER=tavily but TAVILY_API_KEY is empty")
    if config.SEARCH_PROVIDER not in ("brave", "tavily", "duckduckgo"):
        problems.append(f"SEARCH_PROVIDER={config.SEARCH_PROVIDER!r} is not one of brave/tavily/duckduckgo")
    return problems


def main():
    ap = argparse.ArgumentParser(description="Run the forecasting agent once.")
    ap.add_argument("--today", default=date.today().isoformat(),
                    help="Date given to the agent (default: today).")
    ap.add_argument("--max-steps", type=int, default=None,
                    help="Override MAX_STEPS for this run.")
    ap.add_argument("--model", default=None,
                    help="Override GEMINI_MODEL. Free-tier quota is per model, "
                         "so switching models buys a fresh daily budget.")
    args = ap.parse_args()

    if args.max_steps:
        config.MAX_STEPS = args.max_steps
    if args.model:
        config.GEMINI_MODEL = args.model

    problems = preflight()
    if problems:
        print("Cannot start - fix these in .env:\n", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 2

    trace = Trace(question=QUESTION, model=config.GEMINI_MODEL,
                  search_provider=config.SEARCH_PROVIDER)
    print(f"run_id: {trace.run_id}")

    try:
        forecast = run(trace, today=args.today)
    finally:
        trace.write_markdown()

    result = {
        "run_id": trace.run_id,
        "question": QUESTION,
        "model": config.GEMINI_MODEL,
        "search_provider": config.SEARCH_PROVIDER,
        "today": args.today,
        "forecast": forecast.to_dict(),
    }
    trace.write_result(result)
    trace.event("run_end", status=forecast.status)
    trace.write_markdown()

    print(json.dumps(result["forecast"], indent=2)[:2000])
    print(f"\ntrace: runs/{trace.run_id}/")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
