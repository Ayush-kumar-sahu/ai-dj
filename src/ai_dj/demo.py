"""Build a ready-to-play demo set — the whole app pipeline, end to end.

    aidj demo

1. Audition candidates from the Internet Archive (no API key needed).
2. Keep the N whose tempos sit closest together, so the set can actually mix.
3. Analyze each: sections, beats, key, stems.
4. Sequence them with the auto-orderer and save that as the app's queue.
5. Render the mix, plus an MP3 and a credited tracklist.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

import numpy as np

from .arrange import arrange
from .sources import credits
from .sources.archive_org import ArchiveOrgSource
from .sources.base import RemoteTrack, SourceError, display_name

ROOT = Path(__file__).resolve().parents[2]
SONGS_DIR = ROOT / "data" / "songs"
OUTPUT_DIR = ROOT / "data" / "output"
CONFIG_PATH = ROOT / "data" / "config.json"
DEMO_MIX = OUTPUT_DIR / "demo_mix.wav"
DEMO_SUMMARY = OUTPUT_DIR / "demo_summary.json"

#: One octave to fold quick tempo estimates into, so half/double-time reads compare.
TEMPO_OCTAVE = (95.0, 190.0)

Log = Callable[[str], None]


# ------------------------------------------------------------ tempo screening


def fold_tempo(bpm: float) -> float:
    lo, hi = TEMPO_OCTAVE
    while bpm < lo:
        bpm *= 2
    while bpm >= hi:
        bpm /= 2
    return bpm


def quick_tempo(path: Path) -> float | None:
    """Cheap BPM read from one minute mid-track — seconds, versus minutes for full analysis."""
    import librosa

    try:
        duration = librosa.get_duration(path=str(path))
        offset = max(0.0, min(duration / 2 - 30, duration - 60))
        y, sr = librosa.load(str(path), sr=22050, mono=True, offset=offset, duration=60)
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        bpm = float(np.atleast_1d(tempo)[0])
    except Exception:
        return None
    return fold_tempo(bpm) if bpm > 0 else None


def tightest_set(tempos: dict[Path, float], n: int) -> list[Path]:
    """The n tracks whose tempos sit closest together, by ratio of fastest to slowest."""
    ranked = sorted(tempos.items(), key=lambda kv: kv[1])
    if len(ranked) <= n:
        return [p for p, _ in ranked]
    best = min(range(len(ranked) - n + 1),
               key=lambda i: ranked[i + n - 1][1] / ranked[i][1])
    return [p for p, _ in ranked[best:best + n]]


# -------------------------------------------------------------- persistence


def save_queue(names: list[str]) -> None:
    """Hand the running order to the web app, which restores its queue from here."""
    cfg = {}
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text())
        except json.JSONDecodeError:
            cfg = {}
    cfg["queue"] = names
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


# ------------------------------------------------------------------- build


def build_demo(n: int = 10, candidates: int = 20, render: bool = True,
               log: Log = print) -> dict:
    t0 = time.time()
    SONGS_DIR.mkdir(parents=True, exist_ok=True)
    preexisting = {p.name for p in SONGS_DIR.iterdir()}
    source = ArchiveOrgSource()

    # 1 — audition
    log(f"Searching the Internet Archive for {candidates} remixable dance tracks…")
    found = source.search(limit=candidates, min_duration=180, max_duration=480,
                          max_per_release=1)
    if not found:
        raise SourceError("The Internet Archive returned no usable tracks")

    fetched: dict[Path, RemoteTrack] = {}
    for t in found:
        try:
            path = source.download(t, SONGS_DIR)
        except SourceError as e:
            log(f"  skipped {t.label}: {e}")
            continue
        credits.record(t, path)
        fetched[path] = t
        log(f"  ↓ {t.label}  ({t.license_name})")

    # 2 — keep a set that can mix
    log("Screening tempo to pick a set that mixes cleanly…")
    tempos: dict[Path, float] = {}
    for path in fetched:
        bpm = quick_tempo(path)
        if bpm:
            tempos[path] = bpm
            log(f"  ~{bpm:5.1f} BPM  {display_name(path)}")
    chosen = tightest_set(tempos, n)
    spread = (max(tempos[p] for p in chosen) / min(tempos[p] for p in chosen) - 1) * 100
    log(f"Kept {len(chosen)} tracks within a {spread:.1f}% tempo spread")

    for path in fetched:  # the rest were only auditioning
        if path not in chosen and path.name not in preexisting:
            path.unlink(missing_ok=True)
            credits.forget(path)

    # 3–5 — analyze, sequence and render: the same pipeline the web app's set builder uses
    def progress(stage: str, frac: float, detail: dict) -> None:
        if stage == "rendering" and detail.get("step"):
            log(f"  {frac * 100:3.0f}%  {detail['step']}")

    result = arrange(chosen, DEMO_MIX, log=log, progress=progress, render=render)
    save_queue(result["queue"])
    summary = {
        "built_at": time.strftime("%Y-%m-%d %H:%M"),
        "library": [p.name for p in chosen],
        **result,
    }

    summary["seconds"] = round(time.time() - t0)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DEMO_SUMMARY.write_text(json.dumps(summary, indent=2))
    log(f"Demo built in {summary['seconds'] / 60:.1f} min")
    return summary
