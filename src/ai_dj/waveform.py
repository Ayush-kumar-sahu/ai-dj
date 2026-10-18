"""Downsampled peak envelopes for drawing waveforms, cached to disk.

Reading peaks straight off the file with soundfile.blocks avoids a full librosa decode
+ resample, which matters when the Library tab draws a dozen waveforms per rerun.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import soundfile as sf

from . import cache

PEAKS_DIR = cache.CACHE_ROOT / "peaks"
DEFAULT_POINTS = 900


def peaks(audio_path: Path, points: int = DEFAULT_POINTS) -> list[float]:
    """Peak amplitude per time bucket, normalised to 0..1. Cached per file+resolution."""
    audio_path = Path(audio_path).resolve()
    cached = _load(audio_path, points)
    if cached is not None:
        return cached

    try:
        values = _peaks_via_soundfile(audio_path, points)
    except Exception:
        values = _peaks_via_librosa(audio_path, points)

    _save(audio_path, points, values)
    return values


def _peaks_via_soundfile(audio_path: Path, points: int) -> list[float]:
    info = sf.info(str(audio_path))
    if info.frames <= 0:
        raise ValueError("empty file")

    block = max(1, info.frames // points)
    out: list[float] = []
    for chunk in sf.blocks(str(audio_path), blocksize=block, dtype="float32",
                           always_2d=True, fill_value=0.0):
        if chunk.size:
            out.append(float(np.abs(chunk).max()))
    if not out:
        raise ValueError("no audio decoded")
    return _normalise(out, points)


def _peaks_via_librosa(audio_path: Path, points: int) -> list[float]:
    import librosa

    y, _ = librosa.load(str(audio_path), sr=8000, mono=True)
    if y.size == 0:
        return [0.0] * points
    block = max(1, y.size // points)
    usable = (y.size // block) * block
    folded = np.abs(y[:usable]).reshape(-1, block).max(axis=1)
    return _normalise(folded.tolist(), points)


def _normalise(values: list[float], points: int) -> list[float]:
    arr = np.asarray(values, dtype=np.float32)
    # Resample to exactly `points` so every waveform shares an x-axis.
    if arr.size != points:
        arr = np.interp(np.linspace(0, arr.size - 1, points),
                        np.arange(arr.size), arr).astype(np.float32)
    peak = float(arr.max())
    if peak > 0:
        arr = arr / peak
    return [round(float(v), 4) for v in arr]


def _cache_file(audio_path: Path, points: int) -> Path:
    PEAKS_DIR.mkdir(parents=True, exist_ok=True)
    return PEAKS_DIR / f"{audio_path.stem}.{cache.file_key(audio_path)}.{points}.json"


def _load(audio_path: Path, points: int) -> list[float] | None:
    p = _cache_file(audio_path, points)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _save(audio_path: Path, points: int, values: list[float]) -> None:
    try:
        _cache_file(audio_path, points).write_text(json.dumps(values))
    except OSError:
        pass  # a missing waveform cache is cosmetic, never fatal
