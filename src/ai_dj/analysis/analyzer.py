"""Top-level analysis: structure + key + stems + per-segment features, with caching."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

from .. import cache
from ..types import Segment, TrackAnalysis
from . import key as key_mod
from . import stems as stems_mod
from . import structure as structure_mod


def analyze(audio_path: Path, run_stems: bool = True, force: bool = False) -> TrackAnalysis:
    """Full analysis pipeline. Returns cached result unless force=True."""
    audio_path = audio_path.resolve()

    if not force:
        cached = cache.load_analysis(audio_path)
        if cached is not None:
            if run_stems and not cached.stems_dir:
                cached = _add_stems(cached, audio_path)
                cache.save_analysis(cached)
            return cached

    # Hand allin1 the stem cache so its own Demucs pass becomes our stems too.
    stems_out = cache.stems_path(audio_path) if run_stems else None
    struct = structure_mod.analyze_structure(audio_path, stems_out=stems_out)
    camelot, conf = key_mod.detect_key(audio_path)

    info = sf.info(str(audio_path))
    rms_per_seg, centroid_per_seg = _segment_features(audio_path, struct["segments"])

    analysis = TrackAnalysis(
        path=str(audio_path),
        sr=info.samplerate,
        duration=info.frames / info.samplerate,
        bpm=struct["bpm"],
        beats=struct["beats"],
        downbeats=struct["downbeats"],
        segments=struct["segments"],
        camelot=camelot,
        key_confidence=conf,
        rms_per_segment=rms_per_seg,
        centroid_per_segment=centroid_per_seg,
    )

    if run_stems:
        analysis = _add_stems(analysis, audio_path)

    cache.save_analysis(analysis)
    return analysis


def _add_stems(analysis: TrackAnalysis, audio_path: Path) -> TrackAnalysis:
    out_dir = cache.stems_path(audio_path)
    stems_mod.separate(audio_path, out_dir)
    analysis.stems_dir = str(out_dir)
    return analysis


def _segment_features(audio_path: Path, segments: list[Segment]) -> tuple[dict, dict]:
    """Compute mean RMS and spectral centroid per segment (mono, 22050 Hz is enough)."""
    import librosa

    y, sr = librosa.load(str(audio_path), sr=22050, mono=True)
    rms = {}
    centroid = {}
    for i, seg in enumerate(segments):
        s, e = int(seg.start * sr), int(seg.end * sr)
        chunk = y[s:e]
        if chunk.size == 0:
            continue
        key = f"{i}:{seg.label}"
        rms[key] = float(np.sqrt(np.mean(chunk**2)))
        centroid[key] = float(librosa.feature.spectral_centroid(y=chunk, sr=sr).mean())
    return rms, centroid
