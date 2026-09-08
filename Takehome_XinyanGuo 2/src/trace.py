"""Run tracing.

Every run gets a directory under runs/<run_id>/ containing:
  trace.jsonl  - one JSON object per event, in order, append-only
  trace.md     - the same run rendered for a human reader
  result.json  - the final forecast (or the partial one, if the run degraded)

The JSONL is the primary artefact: it is what makes a run reproducible and
auditable after the fact. Nothing is buffered until the end - each event is
flushed as it happens, so a crashed run still leaves a readable trace.
"""
import json
import os
import time
import uuid
from datetime import datetime, timezone

RUNS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runs")


def _now():
    return datetime.now(timezone.utc).isoformat()


class Trace:
    def __init__(self, question: str, model: str, search_provider: str, base_dir: str = None):
        self.run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6]}"
        # base_dir lets the offline test write elsewhere; runs/ holds real runs only.
        self.dir = os.path.join(base_dir or RUNS_DIR, self.run_id)
        os.makedirs(self.dir, exist_ok=True)
        self.path = os.path.join(self.dir, "trace.jsonl")
        self.t0 = time.time()
        self.events = []
        self.event(
            "run_start",
            question=question,
            model=model,
            search_provider=search_provider,
        )

    def event(self, kind: str, **payload):
        rec = {
            "ts": _now(),
            "elapsed_s": round(time.time() - self.t0, 3),
            "seq": len(self.events),
            "kind": kind,
            **payload,
        }
        self.events.append(rec)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        return rec

    def write_result(self, result: dict):
        with open(os.path.join(self.dir, "result.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False, default=str)

    def write_markdown(self):
        """Render the trace for a human. Lossy on purpose; JSONL is the source."""
        lines = [f"# Run `{self.run_id}`", ""]
        for e in self.events:
            head = f"### [{e['seq']}] {e['kind']}  _(+{e['elapsed_s']}s)_"
            lines.append(head)
            for k, v in e.items():
                if k in ("ts", "elapsed_s", "seq", "kind"):
                    continue
                s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str)
                if len(s) > 1500:
                    s = s[:1500] + f"\n... [truncated, {len(s)} chars total]"
                lines.append(f"**{k}:**\n\n```\n{s}\n```\n")
            lines.append("")
        with open(os.path.join(self.dir, "trace.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
