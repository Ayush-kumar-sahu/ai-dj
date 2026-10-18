"""Score how well track A's outro mixes into track B's intro."""

from __future__ import annotations

from .analysis.key import camelot_distance
from .types import TrackAnalysis

# Lower = better. A score of 0.0 is a perfect mix.
# Rough scale: each term is tuned so a "bad" case contributes a few points, which
# keeps any single dimension from swamping the others when ranking a running order.
WEIGHTS = {
    "bpm": 1.0,        # per percent of BPM difference
    "key": 0.5,        # per Camelot wheel step (distance maxes out at 7)
    "energy": 0.3,     # per unit RMS difference (RMS is roughly 0..0.3)
    "key_unknown": 1.5,
    "missing_outro": 2.0,
    "missing_intro": 2.0,
}

MAX_BPM_PCT = 6.0  # outside this, time-stretch starts to sound artifacted


def score(a: TrackAnalysis, b: TrackAnalysis) -> tuple[float, dict[str, float]]:
    """Lower score = better mix. Returns (score, breakdown)."""
    breakdown: dict[str, float] = {}

    bpm_pct = abs(a.bpm - b.bpm) / a.bpm * 100
    breakdown["bpm"] = WEIGHTS["bpm"] * bpm_pct
    if bpm_pct > MAX_BPM_PCT:
        breakdown["bpm"] += 5.0  # hard penalty

    if a.camelot and b.camelot:
        breakdown["key"] = WEIGHTS["key"] * camelot_distance(a.camelot, b.camelot)
    else:
        # Don't pretend to know. A mild flat cost beats guessing a wheel distance.
        breakdown["key_unknown"] = WEIGHTS["key_unknown"]

    a_outro = a.last_outro()
    b_intro = b.first_intro()

    if a_outro is None:
        breakdown["missing_outro"] = WEIGHTS["missing_outro"]
    if b_intro is None:
        breakdown["missing_intro"] = WEIGHTS["missing_intro"]

    if a_outro and b_intro:
        a_key = _segment_key(a, a_outro)
        b_key = _segment_key(b, b_intro)
        a_rms = a.rms_per_segment.get(a_key, 0.0)
        b_rms = b.rms_per_segment.get(b_key, 0.0)
        breakdown["energy"] = WEIGHTS["energy"] * abs(a_rms - b_rms) * 100

    total = sum(breakdown.values())
    return total, breakdown


def _segment_key(track: TrackAnalysis, target) -> str:
    for i, s in enumerate(track.segments):
        if s.start == target.start and s.end == target.end:
            return f"{i}:{s.label}"
    return ""
