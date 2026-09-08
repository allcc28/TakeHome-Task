"""Summarise every run in runs/ as one table.

    .venv/bin/python -m tests.summarise_runs

Reads trace.jsonl + result.json per run. Used to write spec.md section 10, and
kept because "read every trace by hand" does not scale past about three runs.
"""
import glob
import json
import os
import sys


def load(run_dir):
    events = []
    with open(os.path.join(run_dir, "trace.jsonl"), encoding="utf-8") as f:
        for line in f:
            events.append(json.loads(line))
    result = None
    rp = os.path.join(run_dir, "result.json")
    if os.path.exists(rp):
        result = json.load(open(rp, encoding="utf-8"))
    return events, result


def summarise(run_dir):
    events, result = load(run_dir)
    kinds = [e["kind"] for e in events]
    start = next((e for e in events if e["kind"] == "run_start"), {})
    fc = (result or {}).get("forecast", {})
    searches = [e for e in events if e["kind"] == "tool_call" and e["tool"] == "web_search"]
    fetches = [e for e in events if e["kind"] == "tool_call" and e["tool"] == "fetch_page"]
    tool_fails = [e for e in events if e["kind"] == "tool_result" and not e.get("ok")]
    return {
        "run": os.path.basename(run_dir),
        "model": (result or {}).get("model") or start.get("model", "?"),
        "steps": kinds.count("step_start"),
        "searches": len(searches),
        "fetches": len(fetches),
        "tool_fails": len(tool_fails),
        "model_errors": kinds.count("model_error"),
        "compactions": kinds.count("context_compacted"),
        "paced_s": round(sum(e.get("waited_s", 0) for e in events if e["kind"] == "model_paced"), 1),
        "elapsed_s": round(events[-1]["elapsed_s"], 1) if events else 0,
        "status": fc.get("status", "?"),
        "median": fc.get("median_seats"),
        "p_maj": fc.get("p_republican_majority"),
        "probs": fc.get("probabilities"),
        "notes": (fc.get("notes") or "")[:60],
    }


def main():
    runs = sorted(glob.glob(os.path.join("runs", "*")))
    runs = [r for r in runs if os.path.isfile(os.path.join(r, "trace.jsonl"))]
    if not runs:
        print("no runs found")
        return 1
    rows = [summarise(r) for r in runs]

    hdr = f"{'run':<24}{'model':<24}{'st':>3}{'srch':>5}{'fetch':>6}{'tf':>4}{'me':>4}{'cmp':>5}{'secs':>7}  {'status':<11}{'med':>5}{'p_maj':>7}"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        print(f"{r['run']:<24}{r['model']:<24}{r['steps']:>3}{r['searches']:>5}{r['fetches']:>6}"
              f"{r['tool_fails']:>4}{r['model_errors']:>4}{r['compactions']:>5}{r['elapsed_s']:>7}  "
              f"{r['status']:<11}{str(r['median']):>5}{str(r['p_maj']):>7}")

    subs = [r for r in rows if r["status"] == "complete" or (r["probs"] and r["notes"].startswith("forced"))]
    real = [r for r in rows if r["probs"] and not r["notes"].startswith("no forecast")]
    if len(real) > 1:
        print("\nspread across runs that produced a real distribution:")
        print(f"{'bucket':>9} " + " ".join(f"{r['run'][-6:]:>7}" for r in real) + "    range")
        labels = ["<=189", "190-199", "200-209", "210-217", "218-225", "226-235", "236-245", ">=246"]
        for i, lbl in enumerate(labels):
            vals = [r["probs"][i] for r in real]
            print(f"{lbl:>9} " + " ".join(f"{v:>7.3f}" for v in vals) + f"    {max(vals)-min(vals):.3f}")
        for key in ("median", "p_maj"):
            vals = [r[key] for r in real if r[key] is not None]
            if vals:
                print(f"{key:>9} " + " ".join(f"{v:>7}" for v in vals) + f"    {max(vals)-min(vals):.4g}")
    _ = subs
    return 0


if __name__ == "__main__":
    sys.exit(main())
