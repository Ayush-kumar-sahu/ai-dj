"""Turn a pile of tracks into a mixed set: analyze, keep what chains, order, render.

Shared by `aidj demo` and the web app's set builder, so both make the same cuts.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from . import audio, cache, compatibility, ordering
from .analysis.analyzer import analyze
from .render import render_queue, tracklist_path
from .sources.base import display_name
from .types import TrackAnalysis

#: Biggest tempo step between neighbouring tracks the time-stretch handles cleanly.
MAX_TEMPO_STEP = compatibility.MAX_BPM_PCT / 100
#: Planning figure for a track that still needs analysis (measured ~3 min on an M2).
DEFAULT_ANALYSIS_SECONDS = 180.0

Log = Callable[[str], None]
#: (stage, fraction complete 0..1, details for a UI: track names, counts, ETA…)
Progress = Callable[[str, float, dict], None]


class ArrangeError(RuntimeError):
    """The tracks can't be made into a set (e.g. fewer than two that mix)."""


def is_analyzed(path: Path) -> bool:
    a = cache.load_analysis(path)
    return a is not None and bool(a.stems_dir)


def coherent_queue(tracks: list[TrackAnalysis], log: Log) -> list[TrackAnalysis]:
    """The largest group of tracks that chains with every tempo step within the limit.

    A set can drift a long way — 108 → 129 BPM is an ordinary build — as long as
    each neighbouring pair is close. Sorted by BPM, the set splits wherever the gap
    to the next track exceeds the stretch limit; the biggest piece is mixable.
    """
    if len(tracks) < 3:
        return tracks
    ranked = sorted(tracks, key=lambda t: t.bpm)
    clusters = [[ranked[0]]]
    for prev, cur in zip(ranked, ranked[1:]):
        if (cur.bpm - prev.bpm) / prev.bpm > MAX_TEMPO_STEP:
            clusters.append([])
        clusters[-1].append(cur)
    best = max(clusters, key=len)
    if len(best) < 2:
        return tracks
    keep = {id(t) for t in best}
    for t in tracks:
        if id(t) not in keep:
            log(f"  sitting out of the mix (library only): {display_name(t.path)} at "
                f"{t.bpm:.1f} BPM — no neighbour within {MAX_TEMPO_STEP:.0%}")
    return [t for t in tracks if id(t) in keep]


def arrange(paths: list[Path], out_wav: Path, *, log: Log = print,
            progress: Progress | None = None, render: bool = True) -> dict:
    """Analyze → keep what chains → order → render → MP3. Returns a result summary."""
    report = progress or (lambda stage, frac, detail: None)
    paths = [Path(p) for p in paths]
    fresh = {p for p in paths if not is_analyzed(p)}
    # Analysis dominates the run time when there is any to do.
    share = 0.85 if fresh else 0.05
    seconds: list[float] = []
    analyses: list[TrackAnalysis] = []
    failed: list[dict] = []

    for i, p in enumerate(paths, 1):
        pending = len([q for q in paths[i - 1:] if q in fresh])
        per_track = sum(seconds) / len(seconds) if seconds else DEFAULT_ANALYSIS_SECONDS
        report("analyzing", share * (i - 1) / len(paths),
               {"index": i, "total": len(paths), "track": display_name(p),
                "fresh": p in fresh, "eta_seconds": round(pending * per_track)})
        t1 = time.time()
        log(f"[{i}/{len(paths)}] Analyzing {display_name(p)} …")
        try:
            a = analyze(p, run_stems=True)
        except Exception as e:  # one bad file shouldn't sink the set
            failed.append({"track": p.name, "reason": f"analysis failed: {e}"})
            log(f"  ✗ analysis failed: {e}")
            continue
        if p in fresh:
            seconds.append(time.time() - t1)
        analyses.append(a)
        log(f"  ✓ {a.bpm:.1f} BPM · {a.camelot or '?'} · {len(a.segments)} sections · "
            f"{time.time() - t1:.0f}s")

    report("sequencing", share, {"analyzed": len(analyses)})
    queue = coherent_queue(analyses, log)
    kept = {id(a) for a in queue}
    sitting_out = [{"track": Path(a.path).name, "bpm": round(a.bpm, 1),
                    "reason": f"{a.bpm:.0f} BPM — no other track within {MAX_TEMPO_STEP:.0%}"}
                   for a in analyses if id(a) not in kept]
    if len(queue) < 2:
        raise ArrangeError("Need at least two tracks that can be mixed together "
                           f"(analyzed {len(analyses)}, failed {len(failed)}).")
    order, cost = ordering.optimal_order(queue)
    queue = [queue[i] for i in order]
    log("Running order:")
    for i, a in enumerate(queue, 1):
        log(f"  {i:2}. {a.bpm:6.1f} BPM  {a.camelot or '?':>3}  {display_name(a.path)}")

    result = {"queue": [Path(a.path).name for a in queue], "sitting_out": sitting_out,
              "failed": failed, "order_cost": round(cost, 2),
              "mix": None, "mp3": None, "tracklist": None}
    if not render:
        return result

    log(f"Rendering the {len(queue)}-track mix…")
    render_queue([Path(a.path) for a in queue], out_wav,
                 progress=lambda msg, f: report("rendering", share + (0.97 - share) * f,
                                                {"step": msg}))
    report("encoding", 0.97, {})
    log("Encoding MP3 for playback and sharing…")
    mp3 = audio.encode_mp3(out_wav)
    result.update(mix=str(out_wav), mp3=str(mp3), tracklist=str(tracklist_path(out_wav)))
    report("done", 1.0, {})
    return result
