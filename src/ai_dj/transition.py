"""Stem-aware transition engine for EDM/House.

Mix philosophy (per-stem, all phase-locked on downbeats):
    drums   — equal-power crossfade across the whole transition
    bass    — HARD swap at p=0.5 on a downbeat (no two basslines together → no mud)
    vocals  — no overlap: A out by p=0.5, B in from p=0.5
    other   — equal-power crossfade across the whole transition

This is the "frequency-balanced" swap the user described, but using stems
(cleaner separation than 3-band EQ filters):
    Lows  ≈ bass stem      → hard swap
    Mids  ≈ vocals + other → vocals exclusive, other crossfade
    Highs ≈ drum hats / synth tops in `other` → crossfade
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from . import audio
from .types import TrackAnalysis, TransitionPlan

MIN_TRANSITION_BARS = 16
MAX_TRANSITION_BARS = 64
BARS_PER_DOWNBEAT = 1  # we treat each downbeat as a bar (4/4 EDM/house assumption)
BASS_SWAP_PROGRESS = 0.5
VOCAL_HANDOFF_PROGRESS = 0.5
#: When allin1 labels no intro/outro, mix over this many bars at the edge instead.
FALLBACK_EDGE_BARS = 32


def plan_transition(a: TrackAnalysis, b: TrackAnalysis, score: float = 0.0,
                    score_breakdown: dict | None = None,
                    a_not_before: float = 0.0) -> TransitionPlan:
    """Plan the A→B blend.

    `a_not_before` is where A's own incoming transition finished. Mixing out any
    earlier would replay part of A — on a short track, or one whose intro and outro
    labels sit close together, the two windows can overlap. render.plan_queue chains it.
    """
    a_out_start, a_out_end = outro_window(a)
    b_in_start, b_in_end = intro_window(b)
    a_out_start = max(a_out_start, a_not_before)
    a_out_end = max(a_out_end, a_out_start)

    a_bar = 4 * 60 / a.bpm
    b_bar = 4 * 60 / b.bpm

    a_outro_bars = int((a_out_end - a_out_start) / a_bar)
    b_intro_bars = int((b_in_end - b_in_start) / b_bar)
    transition_bars = max(MIN_TRANSITION_BARS, min(MAX_TRANSITION_BARS,
                                                    min(a_outro_bars, b_intro_bars)))
    if transition_bars < MIN_TRANSITION_BARS:
        transition_bars = min(a_outro_bars, b_intro_bars)  # take what we can get

    a_db = _first_downbeat_at_or_after(a, a_out_start)
    b_db = _first_downbeat_at_or_after(b, b_in_start)
    if a_db is None and a.downbeats:
        a_db = a_out_start  # pushed past A's last downbeat: blend unaligned rather than fail
    if a_db is None or b_db is None:
        raise ValueError("No downbeats found inside outro/intro")

    a_end = a_db + transition_bars * a_bar
    music_end = _music_end(a)
    if a_end > music_end:
        # A's outro is shorter than the blend. Start earlier, on a downbeat, so the
        # blend ends where A's music does — otherwise A runs out mid-blend and, if
        # it's still loud there, cuts to silence. Never before A finished mixing in.
        latest = music_end - transition_bars * a_bar
        fits = [d for d in a.downbeats if a_not_before <= d <= latest]
        if fits:
            a_db = fits[-1]
            a_end = a_db + transition_bars * a_bar
    b_end = b_db + transition_bars * b_bar

    # Snap to incoming track's BPM so B continues seamlessly after the transition;
    # only A is time-stretched.
    common_bpm = b.bpm
    return TransitionPlan(
        track_a_path=a.path,
        track_b_path=b.path,
        a_transition_start=a_db,
        a_transition_end=a_end,
        b_transition_start=b_db,
        b_transition_end=b_end,
        transition_bars=transition_bars,
        common_bpm=common_bpm,
        a_stretch_curve=[a.bpm / common_bpm],
        score=score,
        score_breakdown=score_breakdown or {},
    )


def render_transition(plan: TransitionPlan, a: TrackAnalysis, b: TrackAnalysis,
                      sr: int = 44100) -> np.ndarray:
    """Return the transition region as a stereo float32 array."""
    if not a.stems_dir or not b.stems_dir:
        raise ValueError("Both tracks need stems separated before rendering")

    a_stems, a_sr = audio.load_stems(Path(a.stems_dir))
    b_stems, b_sr = audio.load_stems(Path(b.stems_dir))
    if a_sr != sr or b_sr != sr:
        raise ValueError(f"Stem SR mismatch with target ({a_sr}/{b_sr} vs {sr})")

    a_slice = {n: _slice(s, sr, plan.a_transition_start, plan.a_transition_end)
               for n, s in a_stems.items()}
    b_slice = {n: _slice(s, sr, plan.b_transition_start, plan.b_transition_end)
               for n, s in b_stems.items()}

    # time_stretch factor > 1 → output faster/shorter. We want A's output at common_bpm,
    # so factor = common_bpm / a.bpm.
    a_factor = plan.common_bpm / a.bpm
    a_slice = {n: audio.time_stretch(s, sr, a_factor) for n, s in a_slice.items()}
    # B is not stretched (common_bpm == b.bpm by design).

    target_len = max(max(s.shape[0] for s in a_slice.values()),
                     max(s.shape[0] for s in b_slice.values()))
    a_slice = {n: audio.pad_to(s, target_len) for n, s in a_slice.items()}
    b_slice = {n: audio.pad_to(s, target_len) for n, s in b_slice.items()}

    n = target_len
    swap_idx = int(n * BASS_SWAP_PROGRESS)
    vocal_idx = int(n * VOCAL_HANDOFF_PROGRESS)

    out = np.zeros((n, 2), dtype=np.float32)

    fade_out = audio.equal_power_fade(n, fade_in=False)
    fade_in = audio.equal_power_fade(n, fade_in=True)
    out += audio.apply_envelope(a_slice["drums"], fade_out)
    out += audio.apply_envelope(b_slice["drums"], fade_in)
    out += audio.apply_envelope(a_slice["other"], fade_out)
    out += audio.apply_envelope(b_slice["other"], fade_in)

    bass = np.zeros_like(out)
    bass[:swap_idx] = a_slice["bass"][:swap_idx]
    bass[swap_idx:] = b_slice["bass"][swap_idx:]
    out += bass

    vocals = np.zeros_like(out)
    vocals[:vocal_idx] = a_slice["vocals"][:vocal_idx]
    vocals[vocal_idx:] = b_slice["vocals"][vocal_idx:]
    out += vocals

    peak = np.max(np.abs(out))
    if peak > 0.99:
        out *= 0.99 / peak
    return out


def outro_window(track: TrackAnalysis) -> tuple[float, float]:
    """Where to mix out: the labelled outro, else the last bars before trailing silence.

    allin1 does not label an intro/outro on every track — on real audio it can
    return just start → inst → … → end. A DJ would still mix the final 32 bars, so
    that is the fallback rather than refusing to plan the transition.
    """
    seg = track.last_outro()
    if seg is not None:
        return seg.start, seg.end
    end = _music_end(track)
    return max(0.0, end - FALLBACK_EDGE_BARS * 4 * 60 / track.bpm), end


def intro_window(track: TrackAnalysis) -> tuple[float, float]:
    """Where to mix in: the labelled intro, else the first bars after leading silence."""
    seg = track.first_intro()
    if seg is not None:
        return seg.start, seg.end
    start = _music_start(track)
    return start, min(track.duration, start + FALLBACK_EDGE_BARS * 4 * 60 / track.bpm)


def _music_start(track: TrackAnalysis) -> float:
    """First moment past allin1's 'start' (leading silence) segment."""
    for seg in track.segments:
        if seg.label != "start":
            return seg.start
    return 0.0


def _music_end(track: TrackAnalysis) -> float:
    """Last moment before allin1's 'end' (trailing silence) segment."""
    for seg in reversed(track.segments):
        if seg.label != "end":
            return seg.end
    return track.duration


def _first_downbeat_at_or_after(track: TrackAnalysis, t: float) -> float | None:
    for d in track.downbeats:
        if d >= t:
            return d
    return None


def _slice(samples: np.ndarray, sr: int, start: float, end: float) -> np.ndarray:
    s = max(0, int(start * sr))
    e = min(samples.shape[0], int(end * sr))
    return samples[s:e]
