"""Thin wrapper around the runtime model (Gemini via Google AI Studio).

Everything provider-specific lives here, so swapping to an OpenAI-compatible
endpoint (Groq) is a one-file change. Retries are handled here too: on a free
tier, 429 / quota-exhausted is the failure you should actually expect, and a
run should degrade rather than crash.
"""
import random
import re
import time

from google import genai
from google.genai import types

from . import config

RETRYABLE = ("429", "500", "502", "503", "504", "RESOURCE_EXHAUSTED", "UNAVAILABLE", "DEADLINE")

# Google AI Studio free tier is a few requests per minute, per model. Blind
# exponential backoff never clears a 60s window, so we do two things: pace
# requests proactively, and honour the retryDelay the API hands back.
MAX_BACKOFF = 90


def is_daily_quota(msg: str) -> bool:
    """A per-day quota will not clear inside a retry window - waiting on it just
    burns wall-clock. Distinguished from the per-minute quota, which will."""
    return "PerDay" in msg or "per day" in msg.lower()


def retry_delay_from(msg: str):
    """Pull the server's own retry hint out of an error. None if absent."""
    for pat in (r"'retryDelay':\s*'(\d+(?:\.\d+)?)s'", r"retry in (\d+(?:\.\d+)?)s"):
        m = re.search(pat, msg)
        if m:
            return min(float(m.group(1)), MAX_BACKOFF)
    return None


class LLM:
    def __init__(self, trace=None):
        if not config.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not set (see .env.example)")
        self.client = genai.Client(api_key=config.GEMINI_API_KEY)
        self.model = config.GEMINI_MODEL
        self.trace = trace
        self._last_call = 0.0

    def _pace(self):
        """Keep at least MIN_REQUEST_INTERVAL between calls, so a run does not
        walk straight into the per-minute quota it could have avoided."""
        gap = config.MIN_REQUEST_INTERVAL - (time.time() - self._last_call)
        if gap > 0:
            if self.trace:
                self.trace.event("model_paced", waited_s=round(gap, 1))
            time.sleep(gap)

    def generate(self, contents, system_instruction, tools=None, max_retries=4):
        """Return the raw response. Retries transient failures with backoff.

        Raises only if every attempt failed; the caller decides what a failed
        model call means for the run.
        """
        cfg = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.3,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        if tools:
            cfg.tools = [types.Tool(function_declarations=tools)]

        last = None
        for attempt in range(max_retries):
            try:
                self._pace()
                t0 = time.time()
                resp = self.client.models.generate_content(
                    model=self.model, contents=contents, config=cfg
                )
                if self.trace:
                    usage = getattr(resp, "usage_metadata", None)
                    self.trace.event(
                        "model_response",
                        model=self.model,
                        latency_s=round(time.time() - t0, 2),
                        attempt=attempt,
                        prompt_tokens=getattr(usage, "prompt_token_count", None),
                        output_tokens=getattr(usage, "candidates_token_count", None),
                    )
                self._last_call = time.time()
                return resp
            except Exception as e:
                last = e
                self._last_call = time.time()
                msg = f"{type(e).__name__}: {e}"
                retryable = any(code in msg for code in RETRYABLE) and not is_daily_quota(msg)
                hinted = retry_delay_from(msg)
                wait = hinted if hinted is not None else min(2 ** attempt, MAX_BACKOFF)
                if self.trace:
                    self.trace.event(
                        "model_error", attempt=attempt, error=msg[:1200],
                        retryable=retryable, waiting_s=round(wait, 1) if retryable else 0,
                        wait_source="server_hint" if hinted is not None else "backoff",
                        daily_quota=is_daily_quota(msg),
                    )
                if not retryable or attempt == max_retries - 1:
                    break
                time.sleep(wait + random.random())
        raise RuntimeError(f"model call failed after {max_retries} attempts: {last}")


# ---- helpers that keep google.genai types out of the agent loop -----------
def user_text(text: str):
    return types.Content(role="user", parts=[types.Part(text=text)])


def function_result(name: str, payload: dict):
    return types.Content(
        role="user",
        parts=[types.Part.from_function_response(name=name, response=payload)],
    )


def stub_function_result(name: str, note: str):
    """A compacted stand-in for an evicted tool result."""
    return types.Content(
        role="user",
        parts=[types.Part.from_function_response(name=name, response={"ok": True, "compacted": note})],
    )


def split_parts(response):
    """Return (text, [(call_name, args_dict), ...]) from a Gemini response."""
    text_bits, calls = [], []
    cands = getattr(response, "candidates", None) or []
    if not cands:
        return "", []
    content = cands[0].content
    for part in (getattr(content, "parts", None) or []):
        if getattr(part, "function_call", None):
            fc = part.function_call
            calls.append((fc.name, dict(fc.args or {})))
        elif getattr(part, "text", None):
            text_bits.append(part.text)
    return "\n".join(text_bits), calls
