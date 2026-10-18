"""Remember where downloaded tracks came from, so a mix can credit them.

Every Creative Commons licence these catalogs serve carries the BY (attribution)
clause, so a shared mix needs a tracklist naming artist, title, licence and source.
Stored beside the audio as data/songs/credits.json, keyed by filename.
"""

from __future__ import annotations

import json
from pathlib import Path

from .base import RemoteTrack

STORE_NAME = "credits.json"
#: The app's library folder; bare filenames (as the queue stores them) resolve here.
SONGS_DIR = Path(__file__).resolve().parents[3] / "data" / "songs"


def record(track: RemoteTrack, audio_path: Path) -> None:
    store = audio_path.parent / STORE_NAME
    data = _read(store)
    data[audio_path.name] = {
        "artist": track.artist,
        "title": track.name,
        "license": track.license_name,
        "license_url": track.license_url,
        "source": track.source,
        "page_url": track.page_url,
    }
    store.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def lookup(audio_path: str | Path) -> dict | None:
    audio_path = Path(audio_path)
    folder = audio_path.parent if audio_path.parent != Path(".") else SONGS_DIR
    entry = _read(folder / STORE_NAME).get(audio_path.name)
    return dict(entry) if entry else None


def forget(audio_path: Path) -> None:
    store = audio_path.parent / STORE_NAME
    data = _read(store)
    if data.pop(audio_path.name, None) is not None:
        store.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def _read(store: Path) -> dict:
    try:
        return json.loads(store.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
