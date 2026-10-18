"""Internet Archive netlabels — a large Creative Commons catalog that needs no API key.

Complements the Jamendo source: Jamendo has better metadata and curation but requires
a client_id, while archive.org works out of the box. Both serve full-length audio,
which is the non-negotiable requirement for beatmatching an outro into an intro.

Items on archive.org are usually whole releases, so searching walks item metadata and
pulls individual MP3 tracks out of each one.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote, urlparse

import requests

from .base import ImportedPlaylist, RemoteTrack, SourceError, cc_license_name, cc_url_allows_remix

SEARCH_URL = "https://archive.org/advancedsearch.php"
METADATA_URL = "https://archive.org/metadata"
DOWNLOAD_URL = "https://archive.org/download"
USER_AGENT = "ai-dj/0.1 (+local research tool)"
TIMEOUT = 45

#: Preferred first. Archive items often carry several encodings of the same track.
MP3_FORMATS = ["VBR MP3", "320Kbps MP3", "256Kbps MP3", "128Kbps MP3", "64Kbps MP3", "MP3"]

#: Kept under its old name; the check itself lives in base.
remixable = cc_url_allows_remix

DJ_SUBJECTS = ["techno", "house", "tech house", "deep house", "minimal",
               "electro", "trance", "breaks"]

_UNSAFE_ID = re.compile(r"[^\w.-]+")

#: archive.org stores several encodings of one recording as sibling files named
#: "track_64kb.mp3", "track_vbr.mp3" etc. Strip that suffix so they group together,
#: otherwise the same song is downloaded repeatedly at different bitrates.
_DERIVATIVE_SUFFIX = re.compile(r"_(?:\d{2,3}kb(?:ps)?|vbr|cbr|sample)$", re.I)


def _recording_key(filename: str) -> str:
    return _DERIVATIVE_SUFFIX.sub("", Path(filename).stem).strip().lower()


def _duration(raw) -> float:
    """Archive 'length' is either seconds ('243.52') or 'H:MM:SS' / 'M:SS'."""
    if raw is None:
        return 0.0
    text = str(raw).strip()
    if not text:
        return 0.0
    if ":" in text:
        parts = text.split(":")
        try:
            nums = [float(p) for p in parts]
        except ValueError:
            return 0.0
        total = 0.0
        for n in nums:
            total = total * 60 + n
        return total
    try:
        return float(text)
    except ValueError:
        return 0.0


class ArchiveOrgSource:
    name = "archive"

    def __init__(self, client_id: str | None = None):
        # Signature matches the other sources; archive.org needs no credentials.
        self._session = requests.Session()
        self._session.headers["User-Agent"] = USER_AGENT

    def configured(self) -> bool:
        return True

    # ------------------------------------------------------------------ search

    def search(
        self,
        query: str = "",
        *,
        tags: list[str] | None = None,
        limit: int = 12,
        min_duration: int = 120,
        max_duration: int = 600,
        remixable_only: bool = True,
        max_per_release: int = 2,
        collection: str = "netlabels",
        **_ignored,
    ) -> list[RemoteTrack]:
        """Find individual MP3 tracks inside archive.org releases."""
        subjects = tags or DJ_SUBJECTS
        clauses = [f"collection:{collection}", "mediatype:audio"]
        if subjects:
            ors = " OR ".join(f'subject:"{s}"' for s in subjects)
            clauses.append(f"({ors})")
        if query.strip():
            clauses.append(f'"{query.strip()}"')

        params = [
            ("q", " AND ".join(clauses)),
            ("rows", str(max(20, limit * 5))),  # items, not tracks — overshoot
            ("output", "json"),
            ("sort[]", "downloads desc"),
        ]
        for field in ("identifier", "title", "creator", "licenseurl", "year"):
            params.append(("fl[]", field))

        try:
            resp = self._session.get(SEARCH_URL, params=params, timeout=TIMEOUT)
            resp.raise_for_status()
            docs = resp.json()["response"]["docs"]
        except requests.RequestException as e:
            raise SourceError(f"archive.org search failed: {e}") from e
        except (ValueError, KeyError) as e:
            raise SourceError("archive.org returned an unexpected response") from e

        out: list[RemoteTrack] = []
        for doc in docs:
            if len(out) >= limit:
                break
            if remixable_only and not remixable(doc.get("licenseurl")):
                continue
            try:
                out.extend(self._tracks_in(doc, min_duration, max_duration,
                                           max_per_release, limit - len(out)))
            except SourceError:
                continue  # one bad release shouldn't end the search
        return out[:limit]

    _ITEM = re.compile(r"/(?:details|download|embed)/([^/?#]+)")

    def item(self, url: str) -> ImportedPlaylist:
        """Every MP3 track in a pasted archive.org release (an 'item')."""
        m = self._ITEM.search(urlparse(url.strip()).path)
        if not m:
            raise SourceError("Paste a link to one archive.org release (…/details/<name>).")
        identifier = m.group(1)
        meta = self._metadata(identifier)
        item_meta = meta.get("metadata") or {}
        if not item_meta:
            raise SourceError(f"archive.org has no item called '{identifier}'")
        if item_meta.get("mediatype") == "collection":
            raise SourceError("That's a whole collection — open one release in it and paste "
                              "that link instead.")
        doc = {"identifier": identifier, "creator": item_meta.get("creator"),
               "licenseurl": item_meta.get("licenseurl")}
        tracks = self._tracks_in(doc, min_d=30, max_d=3600, max_per_release=500, room=500,
                                 meta=meta)
        if not tracks:
            raise SourceError("That release has no MP3 audio to mix.")
        title = item_meta.get("title") or identifier
        creator = doc["creator"][0] if isinstance(doc["creator"], list) else doc["creator"]
        return ImportedPlaylist(
            title=title[0] if isinstance(title, list) else str(title), source=self.name,
            url=url.strip(), owner=creator, image=f"https://archive.org/services/img/{identifier}",
            tracks=tracks)

    def _metadata(self, identifier: str) -> dict:
        try:
            resp = self._session.get(f"{METADATA_URL}/{identifier}", timeout=TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as e:
            raise SourceError(f"metadata for {identifier} unavailable: {e}") from e

    def _tracks_in(self, doc: dict, min_d: int, max_d: int,
                   max_per_release: int, room: int, meta: dict | None = None) -> list[RemoteTrack]:
        identifier = doc["identifier"]
        if meta is None:
            meta = self._metadata(identifier)

        files = meta.get("files") or []
        item_meta = meta.get("metadata") or {}
        licence = doc.get("licenseurl") or item_meta.get("licenseurl") or ""
        artist = (doc.get("creator") or item_meta.get("creator") or "Unknown artist")
        if isinstance(artist, list):
            artist = artist[0] if artist else "Unknown artist"

        # Group encodings by their source track, then keep the best MP3 of each.
        best: dict[str, dict] = {}
        for f in files:
            fmt = f.get("format", "")
            if fmt not in MP3_FORMATS:
                continue
            key = _recording_key(f.get("name", ""))
            rank = MP3_FORMATS.index(fmt)
            if key not in best or rank < best[key]["_rank"]:
                best[key] = {**f, "_rank": rank}

        picked: list[RemoteTrack] = []
        for key, f in sorted(best.items(), key=lambda kv: kv[1].get("name", "")):
            if len(picked) >= min(max_per_release, room):
                break
            seconds = _duration(f.get("length"))
            if not (min_d <= seconds <= max_d):
                continue
            name = f.get("title") or key
            if isinstance(name, list):
                name = name[0]
            track_artist = f.get("artist") or f.get("creator") or artist
            if isinstance(track_artist, list):
                track_artist = track_artist[0] if track_artist else artist
            fname = f["name"]
            picked.append(RemoteTrack(
                source="archive",
                id=_UNSAFE_ID.sub("_", f"{identifier}_{key}")[:70],
                name=str(name)[:90],
                artist=str(track_artist)[:60],
                duration=seconds,
                license_name=cc_license_name(licence),
                license_url=licence or None,
                page_url=f"https://archive.org/details/{identifier}",
                image=f"https://archive.org/services/img/{identifier}",  # release artwork
                tags=[str(s) for s in (item_meta.get("subject") or [])][:8]
                     if isinstance(item_meta.get("subject"), list)
                     else ([str(item_meta.get("subject"))] if item_meta.get("subject") else []),
                stream_url=f"{DOWNLOAD_URL}/{identifier}/{quote(fname)}",
                download_url=f"{DOWNLOAD_URL}/{identifier}/{quote(fname)}",
                downloadable=True,
            ))
        return picked

    # ---------------------------------------------------------------- download

    def download(self, track: RemoteTrack, dest_dir: Path) -> Path:
        if not track.download_url:
            raise SourceError(f"{track.label} has no download URL")
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / track.filename(".mp3")
        if dest.exists() and dest.stat().st_size > 0:
            return dest

        tmp = dest.with_suffix(dest.suffix + ".part")
        try:
            with self._session.get(track.download_url, stream=True,
                                   timeout=TIMEOUT, allow_redirects=True) as r:
                r.raise_for_status()
                with tmp.open("wb") as fh:
                    for chunk in r.iter_content(chunk_size=1 << 16):
                        fh.write(chunk)
        except requests.RequestException as e:
            tmp.unlink(missing_ok=True)
            raise SourceError(f"Could not download {track.label}: {e}") from e

        if tmp.stat().st_size < 10_000:
            tmp.unlink(missing_ok=True)
            raise SourceError(f"{track.label} downloaded empty")
        tmp.replace(dest)
        return dest
