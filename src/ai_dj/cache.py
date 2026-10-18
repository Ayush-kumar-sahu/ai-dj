from __future__ import annotations

import hashlib
from pathlib import Path

from .types import TrackAnalysis

CACHE_ROOT = Path(__file__).resolve().parents[2] / "data" / "cache"
ANALYSIS_DIR = CACHE_ROOT / "analysis"
STEMS_DIR = CACHE_ROOT / "stems"


def file_key(audio_path: Path) -> str:
    """Content-ish identity for a file: path + size + mtime. Invalidates on edit."""
    stat = audio_path.stat()
    payload = f"{audio_path.resolve()}:{stat.st_size}:{int(stat.st_mtime)}".encode()
    return hashlib.sha1(payload).hexdigest()[:16]


_key = file_key  # backwards-compatible alias


def analysis_path(audio_path: Path) -> Path:
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    return ANALYSIS_DIR / f"{audio_path.stem}.{_key(audio_path)}.json"


def stems_path(audio_path: Path) -> Path:
    p = STEMS_DIR / f"{audio_path.stem}.{_key(audio_path)}"
    p.mkdir(parents=True, exist_ok=True)
    return p


def load_analysis(audio_path: Path) -> TrackAnalysis | None:
    p = analysis_path(audio_path)
    if not p.exists():
        return None
    return TrackAnalysis.model_validate_json(p.read_text())


def save_analysis(analysis: TrackAnalysis) -> Path:
    p = analysis_path(Path(analysis.path))
    p.write_text(analysis.model_dump_json(indent=2))
    return p
