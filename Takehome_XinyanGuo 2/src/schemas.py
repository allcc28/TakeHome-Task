"""Data contracts.

The answer representation is the central design decision in this exercise.
The question ("how many House seats will the Republicans win in 2026?") is a
count, not a yes/no, so the agent must return a *distribution*, not a number.

We represent it as a probability mass function over contiguous seat-count
buckets, plus a derived point estimate and interval. Buckets mirror how Kalshi
and Polymarket actually quote House seat-count markets, which means our output
is directly comparable to a market price and is scorable with a multi-class
Brier or log score. See spec.md for the alternatives considered.
"""
from dataclasses import dataclass, field, asdict
from typing import List, Optional

# Republicans currently hold ~220 of 435; 218 is the majority threshold.
# Buckets are contiguous, exhaustive over 0-435, and mutually exclusive.
BUCKETS: List[tuple] = [
    (0, 189),
    (190, 199),
    (200, 209),
    (210, 217),   # split at the majority line on purpose
    (218, 225),
    (226, 235),
    (236, 245),
    (246, 435),
]

BUCKET_LABELS = [
    f"{lo}-{hi}" if lo != 0 and hi != 435 else (f"<={hi}" if lo == 0 else f">={lo}")
    for lo, hi in BUCKETS
]


@dataclass
class Source:
    url: str
    title: str = ""
    why_it_mattered: str = ""


@dataclass
class Forecast:
    """The agent's final answer."""
    bucket_labels: List[str]
    probabilities: List[float]          # must align with bucket_labels, sum ~1.0
    median_seats: Optional[int] = None
    interval_80: Optional[List[int]] = None   # [low, high]
    p_republican_majority: Optional[float] = None  # P(seats >= 218), derived
    reasoning: str = ""
    key_drivers: List[str] = field(default_factory=list)
    sources: List[Source] = field(default_factory=list)
    status: str = "complete"            # complete | incomplete
    notes: str = ""

    def to_dict(self):
        return asdict(self)


def validate_and_normalise(probs: List[float]) -> tuple:
    """Return (normalised_probs, list_of_warnings). Never raises."""
    warnings = []
    if len(probs) != len(BUCKETS):
        warnings.append(
            f"expected {len(BUCKETS)} probabilities, got {len(probs)}"
        )
        probs = (probs + [0.0] * len(BUCKETS))[: len(BUCKETS)]
    probs = [max(0.0, float(p)) for p in probs]
    total = sum(probs)
    if total <= 0:
        warnings.append("probabilities summed to zero; falling back to uniform")
        return [1.0 / len(BUCKETS)] * len(BUCKETS), warnings
    if abs(total - 1.0) > 0.02:
        warnings.append(f"probabilities summed to {total:.3f}; renormalised")
    return [p / total for p in probs], warnings


def derive_stats(probs: List[float]) -> dict:
    """Median bucket midpoint, 80% interval, and P(majority) from the PMF."""
    cum, median, lo80, hi80 = 0.0, None, None, None
    for (lo, hi), p in zip(BUCKETS, probs):
        prev = cum
        cum += p
        mid = (lo + hi) // 2
        if lo80 is None and cum >= 0.10:
            lo80 = lo
        if median is None and cum >= 0.50:
            median = mid
        if hi80 is None and cum >= 0.90:
            hi80 = hi
        _ = prev
    p_majority = sum(
        p for (lo, hi), p in zip(BUCKETS, probs) if hi >= 218
    )
    return {
        "median_seats": median,
        "interval_80": [lo80, hi80],
        "p_republican_majority": round(p_majority, 4),
    }
