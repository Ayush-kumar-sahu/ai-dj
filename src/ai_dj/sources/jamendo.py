"""Jamendo v3.0 catalog — ~500k Creative Commons tracks with full-length downloads.

Why this one: it is the only large free catalog that hands back *whole tracks* over a
documented API. Preview-clip APIs (Spotify, Deezer, iTunes) are useless here — you
cannot beatmatch an outro you were never given.

Jamendo does not publish BPM or musical key, only a coarse `speed` bucket. That is
fine: this app derives tempo, downbeats, sections and key itself from the audio.

Get a free client_id at https://devportal.jamendo.com/ and either export
JAMENDO_CLIENT_ID or paste it into the sidebar.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import urlparse

import requests

from .base import ImportedPlaylist, RemoteTrack, SourceError, cc_license_name

API_ROOT = "https://api.jamendo.com/v3.0"
USER_AGENT = "ai-dj/0.1 (+local research tool)"
TIMEOUT = 30

#: Jamendo's own tempo buckets, coarse but useful as a pre-filter before real analysis.
SPEEDS = ["verylow", "low", "medium", "high", "veryhigh"]

#: Ordering modes worth exposing. Jamendo wants `boost` for text searches, `order` otherwise.
ORDERS = {
    "Popular": "popularity_total",
    "Trending": "buzzrate",
    "Most downloaded": "downloads_week",
    "Newest": "releasedate_desc",
}

#: `boost` only accepts the popularity-style rankers — anything else must go via `order`.
BOOST_VALUES = {
    "buzzrate", "downloads_week", "downloads_month", "downloads_total",
    "listens_week", "listens_month", "listens_total",
    "popularity_week", "popularity_month", "popularity_total",
}

#: Genre tags that actually return dance material on Jamendo.
DJ_TAGS = [
    "house", "deephouse", "techhouse", "techno", "trance", "electro",
    "edm", "dance", "progressive", "minimal", "drumnbass", "dubstep",
    "disco", "funk", "lounge", "chillout", "ambient", "hiphop",
]

#: Shared with the other catalogs so licence labels read identically everywhere.
_license_name = cc_license_name


class JamendoSource:
    name = "jamendo"

    def __init__(self, client_id: str | None = None):
        self.client_id = (client_id or os.environ.get("JAMENDO_CLIENT_ID") or "").strip()
        self._session = requests.Session()
        self._session.headers["User-Agent"] = USER_AGENT

    def configured(self) -> bool:
        return bool(self.client_id)

    # ------------------------------------------------------------------ search

    def search(
        self,
        query: str = "",
        *,
        tags: list[str] | None = None,
        speed: str | None = None,
        order: str = "popularity_total",
        limit: int = 24,
        offset: int = 0,
        min_duration: int = 120,
        max_duration: int = 600,
        downloadable_only: bool = True,
        remixable_only: bool = True,
    ) -> list[RemoteTrack]:
        """Search the catalog.

        `remixable_only` drops no-derivatives (ND) licences. A DJ mix *is* a derivative
        work, so ND tracks are the ones you cannot legally publish a mix of.
        """
        if not self.configured():
            raise SourceError("No Jamendo client_id set. Get one at devportal.jamendo.com.")

        params: dict[str, object] = {
            "client_id": self.client_id,
            "format": "json",
            "limit": max(1, min(int(limit), 200)),
            "offset": max(0, int(offset)),
            "include": "musicinfo licenses",   # requests encodes the space as '+', as Jamendo expects
            "audioformat": "mp32",             # highest-quality MP3 tier
            "audiodlformat": "mp32",
            "durationbetween": f"{int(min_duration)}_{int(max_duration)}",
        }
        if remixable_only:
            params["ccnd"] = "false"
        if query.strip():
            params["search"] = query.strip()
            # `boost` is the search-aware ranker, but it only accepts popularity fields.
            params["boost" if order in BOOST_VALUES else "order"] = order
        else:
            params["order"] = order
        if tags:
            params["fuzzytags"] = " ".join(tags)
        if speed:
            params["speed"] = speed

        payload = self._get("/tracks/", params)
        tracks = [self._to_track(row) for row in payload.get("results", [])]
        # There is no server-side filter for this; the flag only comes back on results.
        if downloadable_only:
            tracks = [t for t in tracks if t.downloadable]
        return tracks

    def get(self, track_id: str) -> RemoteTrack | None:
        """Look up a single track by its Jamendo id."""
        if not self.configured():
            raise SourceError("No Jamendo client_id set. Get one at devportal.jamendo.com.")
        payload = self._get("/tracks/", {
            "client_id": self.client_id,
            "format": "json",
            "id": track_id,
            "include": "musicinfo licenses",
            "audioformat": "mp32",
            "audiodlformat": "mp32",
        })
        rows = payload.get("results", [])
        return self._to_track(rows[0]) if rows else None

    # Jamendo links look like /playlist/123…, /album/123…, /track/123…, or /list/p123…
    _LINKS = [(re.compile(r"/(?:list/p|playlist/)(\d+)"), "playlist"),
              (re.compile(r"/(?:list/a|album/)(\d+)"), "album"),
              (re.compile(r"/track/(\d+)"), "track")]

    def playlist(self, url: str) -> ImportedPlaylist:
        """Resolve a pasted jamendo.com playlist, album or track link."""
        if not self.configured():
            raise SourceError("Jamendo links need a free client ID — add one in the sidebar "
                              "(devportal.jamendo.com).")
        path = urlparse(url.strip()).path
        kind = ident = None
        for rx, k in self._LINKS:
            m = rx.search(path)
            if m:
                kind, ident = k, m.group(1)
                break
        if kind is None:
            raise SourceError("Paste a Jamendo playlist, album or track link.")
        if kind == "track":
            t = self.get(ident)
            if t is None:
                raise SourceError("Jamendo has no track with that id")
            return ImportedPlaylist(title=t.name, source=self.name, url=url.strip(),
                                    owner=t.artist, image=t.image, tracks=[t])

        endpoint = "/playlists/tracks/" if kind == "playlist" else "/albums/tracks/"
        payload = self._get(endpoint, {
            "client_id": self.client_id, "format": "json", "id": ident, "limit": 200,
            "audioformat": "mp32", "audiodlformat": "mp32",
        })
        rows = payload.get("results") or []
        if not rows:
            raise SourceError(f"Jamendo has no public {kind} with that id")
        parent = rows[0]
        # Album tracks don't repeat the artist or artwork, so inherit them.
        inherited = {"artist_name": parent.get("artist_name") or parent.get("user_name"),
                     "album_image": parent.get("image")}
        return ImportedPlaylist(
            title=parent.get("name") or f"Jamendo {kind}", source=self.name, url=url.strip(),
            owner=parent.get("user_name") or parent.get("artist_name"), image=parent.get("image"),
            tracks=[self._to_track({**inherited, **row}) for row in parent.get("tracks") or []])

    def _get(self, path: str, params: dict) -> dict:
        try:
            resp = self._session.get(f"{API_ROOT}{path}", params=params, timeout=TIMEOUT)
            resp.raise_for_status()
            payload = resp.json()
        except requests.RequestException as e:
            raise SourceError(f"Jamendo request failed: {e}") from e
        except ValueError as e:
            raise SourceError("Jamendo returned a non-JSON response") from e

        headers = payload.get("headers", {})
        if headers.get("status") != "success":
            raise SourceError(headers.get("error_message") or "Jamendo rejected the request")
        return payload

    @staticmethod
    def _to_track(row: dict) -> RemoteTrack:
        info = row.get("musicinfo") or {}
        tag_groups = info.get("tags") or {}
        tags = [t for group in ("genres", "instruments", "vartags")
                for t in (tag_groups.get(group) or [])]

        return RemoteTrack(
            source="jamendo",
            id=str(row.get("id", "")),
            name=row.get("name") or "Untitled",
            artist=row.get("artist_name") or "Unknown artist",
            duration=float(row.get("duration") or 0.0),
            license_name=_license_name(row.get("license_ccurl")),
            license_url=row.get("license_ccurl"),
            page_url=row.get("shareurl"),
            image=row.get("image") or row.get("album_image"),
            tags=tags[:12],
            speed=info.get("speed"),
            stream_url=row.get("audio"),
            download_url=row.get("audiodownload"),
            downloadable=bool(row.get("audiodownload_allowed")),
            unavailable_reason=(None if row.get("audiodownload_allowed")
                                else "the artist hasn't enabled downloads"),
        )

    # ---------------------------------------------------------------- download

    def download(self, track: RemoteTrack, dest_dir: Path) -> Path:
        """Fetch the full MP3 into dest_dir. Returns the existing file if already there."""
        if not track.downloadable:
            raise SourceError(f"{track.label} is not offered for download by the artist")

        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / track.filename(".mp3")
        if dest.exists() and dest.stat().st_size > 0:
            return dest

        urls = [u for u in (track.download_url, self._file_endpoint(track.id)) if u]
        last_error: Exception | None = None
        for url in urls:
            try:
                return self._stream_to(url, dest)
            except (requests.RequestException, SourceError) as e:
                last_error = e
        raise SourceError(f"Could not download {track.label}: {last_error}")

    def _file_endpoint(self, track_id: str) -> str | None:
        if not self.configured():
            return None
        return (f"{API_ROOT}/tracks/file/?client_id={self.client_id}"
                f"&id={track_id}&audioformat=mp32")

    def _stream_to(self, url: str, dest: Path) -> Path:
        tmp = dest.with_suffix(dest.suffix + ".part")
        with self._session.get(url, stream=True, timeout=TIMEOUT, allow_redirects=True) as r:
            r.raise_for_status()
            ctype = r.headers.get("Content-Type", "")
            if "audio" not in ctype and "octet-stream" not in ctype:
                raise SourceError(f"expected audio, got {ctype or 'no content-type'}")
            with tmp.open("wb") as fh:
                for chunk in r.iter_content(chunk_size=1 << 16):
                    fh.write(chunk)

        if tmp.stat().st_size < 10_000:  # a few KB means an error page, not a song
            tmp.unlink(missing_ok=True)
            raise SourceError("download was empty")
        tmp.replace(dest)
        return dest
