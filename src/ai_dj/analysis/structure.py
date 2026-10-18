"""Wraps mir-aidj/all-in-one for section + beat + BPM analysis."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import get_args

from ..types import Segment, SegmentLabel
from .stems import STEM_NAMES

_KNOWN_LABELS = set(get_args(SegmentLabel))


def analyze_structure(audio_path: Path, stems_out: Path | None = None) -> dict:
    """Run All-In-One analyzer. Returns {bpm, beats, downbeats, segments}.

    All-In-One source-separates the track with htdemucs as its first step — the
    same model and settings the stem stage uses. Pass `stems_out` to keep those
    stems instead of throwing them away and running Demucs a second time, which
    roughly halves analysis time.

    Imported lazily — allin1 pulls in torch/madmom, which we don't want at module import.
    """
    import allin1

    # A private scratch dir per call: no collisions between tracks with the same
    # stem, and nothing left in the working directory if allin1 dies mid-run.
    with tempfile.TemporaryDirectory(prefix="aidj-allin1-") as tmp:
        scratch = Path(tmp)
        result = allin1.analyze(
            str(audio_path),
            demix_dir=scratch / "demix",
            spec_dir=scratch / "spec",
            keep_byproducts=True,  # the temp dir is deleted either way
            # allin1's pool spawns one worker per core to parallelise across *files*.
            # We pass one file, so it buys nothing — and spawned workers re-import
            # __main__, which breaks under Streamlit's script runner and stdin scripts.
            multiprocess=False,
        )
        if stems_out is not None:
            _harvest_stems(scratch / "demix" / "htdemucs", audio_path, stems_out)

    # A label we don't know (say, from a newer allin1 model) degrades to "inst"
    # rather than failing validation and discarding minutes of analysis.
    segments = [
        Segment(start=float(s.start), end=float(s.end),
                label=s.label if s.label in _KNOWN_LABELS else "inst")
        for s in result.segments
    ]

    return {
        "bpm": float(result.bpm),
        "beats": [float(b) for b in result.beats],
        "downbeats": [float(d) for d in result.downbeats],
        "segments": segments,
    }


def _harvest_stems(demix_root: Path, audio_path: Path, stems_out: Path) -> None:
    """Move All-In-One's htdemucs output into the stem cache, if it is all there."""
    track_dir = demix_root / audio_path.stem
    if not track_dir.is_dir():
        found = [d for d in demix_root.iterdir() if d.is_dir()] if demix_root.is_dir() else []
        if len(found) != 1:
            return  # unexpected layout: the stem stage will separate from scratch
        track_dir = found[0]

    sources = {name: track_dir / f"{name}.wav" for name in STEM_NAMES}
    if not all(p.is_file() for p in sources.values()):
        return

    stems_out.mkdir(parents=True, exist_ok=True)
    for name, src in sources.items():
        shutil.move(str(src), str(stems_out / f"{name}.wav"))
