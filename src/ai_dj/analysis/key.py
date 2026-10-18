"""Key detection → Camelot notation for harmonic mixing."""

from __future__ import annotations

from pathlib import Path

# Krumhansl-Schmuckler → Camelot mapping
# Camelot wheel: 1A..12A (minor), 1B..12B (major)
_CAMELOT = {
    ("C", "major"): "8B",  ("C", "minor"): "5A",
    ("C#", "major"): "3B", ("C#", "minor"): "12A",
    ("Db", "major"): "3B", ("Db", "minor"): "12A",
    ("D", "major"): "10B", ("D", "minor"): "7A",
    ("D#", "major"): "5B", ("D#", "minor"): "2A",
    ("Eb", "major"): "5B", ("Eb", "minor"): "2A",
    ("E", "major"): "12B", ("E", "minor"): "9A",
    ("F", "major"): "7B",  ("F", "minor"): "4A",
    ("F#", "major"): "2B", ("F#", "minor"): "11A",
    ("Gb", "major"): "2B", ("Gb", "minor"): "11A",
    ("G", "major"): "9B",  ("G", "minor"): "6A",
    ("G#", "major"): "4B", ("G#", "minor"): "1A",
    ("Ab", "major"): "4B", ("Ab", "minor"): "1A",
    ("A", "major"): "11B", ("A", "minor"): "8A",
    ("A#", "major"): "6B", ("A#", "minor"): "3A",
    ("Bb", "major"): "6B", ("Bb", "minor"): "3A",
    ("B", "major"): "1B",  ("B", "minor"): "10A",
}


def detect_key(audio_path: Path) -> tuple[str | None, float]:
    """Return (camelot, confidence). Tries essentia first, falls back to librosa chroma."""
    try:
        return _detect_essentia(audio_path)
    except Exception:
        return _detect_librosa(audio_path)


def _detect_essentia(audio_path: Path) -> tuple[str | None, float]:
    import essentia.standard as es

    audio = es.MonoLoader(filename=str(audio_path), sampleRate=44100)()
    key, scale, strength = es.KeyExtractor()(audio)
    return _CAMELOT.get((key, scale)), float(strength)


def _detect_librosa(audio_path: Path) -> tuple[str | None, float]:
    import librosa
    import numpy as np

    y, sr = librosa.load(str(audio_path), sr=22050, mono=True)
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr).mean(axis=1)

    # Krumhansl-Kessler key profiles
    major = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
    minor = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
    pitches = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

    scores = []
    for i in range(12):
        scores.append((np.corrcoef(np.roll(major, i), chroma)[0, 1], pitches[i], "major"))
        scores.append((np.corrcoef(np.roll(minor, i), chroma)[0, 1], pitches[i], "minor"))

    best = max(scores, key=lambda x: x[0])
    return _CAMELOT.get((best[1], best[2])), float(best[0])


#: Furthest two keys can be: six steps around the wheel plus a mode change.
MAX_CAMELOT_DISTANCE = 7

#: Used when a key is missing. Mid-scale, so an undetected key is a mild unknown
#: rather than a disqualification.
UNKNOWN_KEY_DISTANCE = 3


def _parse(code: str) -> tuple[int, str] | None:
    """'8A' → (8, 'A'). None if it isn't a Camelot code."""
    code = code.strip().upper()
    if len(code) < 2 or code[-1] not in ("A", "B") or not code[:-1].isdigit():
        return None
    number = int(code[:-1])
    return (number, code[-1]) if 1 <= number <= 12 else None


def camelot_distance(a: str | None, b: str | None) -> int:
    """Steps between two keys on the Camelot wheel, 0 (identical) to 7 (opposite).

    The classic compatible moves all score 1: relative major/minor (same number,
    other letter) and ±1 around the wheel (same letter). Anything further is the
    sum of those two costs, so 9A→8B is 2 — a step off a compatible key, not a
    disaster. Returns UNKNOWN_KEY_DISTANCE if either key is missing or malformed.
    """
    if not a or not b:
        return UNKNOWN_KEY_DISTANCE
    pa, pb = _parse(a), _parse(b)
    if pa is None or pb is None:
        return UNKNOWN_KEY_DISTANCE

    (na, la), (nb, lb) = pa, pb
    ring = min((na - nb) % 12, (nb - na) % 12)
    return ring if la == lb else ring + 1
