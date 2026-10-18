"""Common shape for remote music catalogs the app can pull tracks from."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel

_UNSAFE = re.compile(r"[^\w\-.() ]+")
_CC_CODE = re.compile(r"creativecommons\.org/licenses/([a-z\-]+)/([\d.]+)")


_CC_PUBLIC = re.compile(r"creativecommons\.org/publicdomain/(zero|mark)/([\d.]+)")


def cc_license_name(url: str | None) -> str | None:
    """'…/licenses/by-nc-nd/3.0/' → 'CC BY-NC-ND 3.0'; '…/publicdomain/zero/1.0/' → 'CC0 1.0'."""
    if not url:
        return None
    m = _CC_CODE.search(url)
    if m:
        return f"CC {m.group(1).upper()} {m.group(2)}"
    m = _CC_PUBLIC.search(url)
    if m:
        return f"CC0 {m.group(2)}" if m.group(1) == "zero" else f"Public Domain Mark {m.group(2)}"
    return "Custom licence"


class RemoteTrack(BaseModel):
    """One track in a remote catalog, before it lands in the local library."""

    source: str
    id: str
    name: str
    artist: str
    duration: float

    license_name: str | None = None
    license_url: str | None = None
    page_url: str | None = None
    image: str | None = None

    tags: list[str] = []
    speed: str | None = None  # coarse tempo bucket, where the source exposes one

    stream_url: str | None = None
    download_url: str | None = None
    downloadable: bool = False
    #: Why it can't be fetched, in words a person can act on (None when downloadable).
    unavailable_reason: str | None = None

    @property
    def label(self) -> str:
        return f"{self.artist} — {self.name}"

    def filename(self, ext: str = ".mp3") -> str:
        """Stable, filesystem-safe name. The source id keeps re-downloads idempotent."""
        stem = _UNSAFE.sub("", f"{self.artist} - {self.name}").strip()[:80] or "track"
        return f"{stem} [{self.source}-{self.id}]{ext}"



def display_name(path: str | Path) -> str:
    """Human title for a library file: strips the ' [source-id]' tag filename() adds."""
    stem = Path(path).stem
    if stem.endswith("]") and " [" in stem:
        stem = stem[:stem.rindex(" [")]
    return stem


_TRACK_NO = re.compile(r"^\s*\d{1,3}\s*[-–.)_]\s*")


def tidy_title(artist: str, title: str) -> str:
    """Display-only cleanup of catalog titles.

    '01 - Monochromatic - Immobility-' by MonoChromatic → 'Immobility'. Filenames
    keep the raw title, so re-running a download still finds the existing file.
    """
    t = _TRACK_NO.sub("", title).strip()
    a = artist.strip()
    for sep in (" - ", " – ", " — ", "-", "_"):
        prefix = f"{a}{sep}"
        if a and t.lower().startswith(prefix.lower()):
            t = t[len(prefix):]
            break
    return t.strip(" -–—_") or title.strip()


_CC_URL = re.compile(
    r"^https?://(?:www\.)?creativecommons\.org/(licenses|publicdomain)/([a-z+\-]+)")


def cc_url_allows_remix(licence_url: str | None) -> bool:
    """True only for a recognised CC licence URL (or CC0) that permits derivatives.

    A DJ mix is a derivative work, so ND licences are out — and so is a *missing*
    licence: unknown is not the same as permitted.
    """
    if not licence_url:
        return False
    m = _CC_URL.match(licence_url.strip().lower())
    if not m:
        return False
    if m.group(1) == "publicdomain":
        return True
    return "nd" not in m.group(2).split("-")


def allows_remix(track: "RemoteTrack") -> bool:
    """Can a mix containing this track be published? Licence URL when there is one,
    else the licence name (Audius only gives names like 'Attribution CC BY')."""
    if track.license_url:
        return cc_url_allows_remix(track.license_url)
    name = (track.license_name or "").upper()
    if "CC0" in name or "PUBLIC DOMAIN" in name:
        return True
    tokens = set(re.split(r"[^A-Z0-9]+", name))
    no_derivs = "ND" in tokens or "NODERIVATIVES" in name.replace(" ", "")
    return "CC" in tokens and "BY" in tokens and not no_derivs


class ImportedPlaylist(BaseModel):
    """A playlist or album pulled from a catalog, before any audio is downloaded."""

    title: str
    source: str
    url: str
    owner: str | None = None
    image: str | None = None
    tracks: list[RemoteTrack]

    @property
    def importable(self) -> list[RemoteTrack]:
        return [t for t in self.tracks if t.downloadable]

@runtime_checkable
class MusicSource(Protocol):
    """A searchable catalog that can deposit full-length audio into a directory."""

    name: str

    def configured(self) -> bool:
        """False when the source still needs credentials before it will answer."""
        ...

    def search(self, query: str = "", **filters) -> list[RemoteTrack]:
        ...

    def download(self, track: RemoteTrack, dest_dir: Path) -> Path:
        ...


class SourceError(RuntimeError):
    """Raised when a catalog rejects a request or returns something unusable."""
