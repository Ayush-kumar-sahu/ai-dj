"""Audius — an open, artist-run music platform with a public API and no key needed.

Playlists and albums resolve from a pasted audius.co link. Streaming is open, but
downloading is each artist's choice: only tracks flagged `is_downloadable` (and not
download-gated behind a follow or purchase) are fetched. The API enforces the same
line — /download returns 404 for anything else — so this source never pulls audio
from the stream endpoint to get around it.

Most Audius tracks are "All rights reserved" even when downloadable: fine for a
personal mix, not one you publish. `base.allows_remix` reports which is which.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import requests

from .base import ImportedPlaylist, RemoteTrack, SourceError

API_ROOT = "https://api.audius.co/v1"
APP_NAME = "ai-dj"
USER_AGENT = "ai-dj/0.1 (+local research tool)"
TIMEOUT = 45

#: Audio types the download endpoint can hand back → file extension to save under.
_EXT = {"audio/mpeg": ".mp3", "audio/mp3": ".mp3", "audio/wav": ".wav", "audio/x-wav": ".wav",
        "audio/wave": ".wav", "audio/flac": ".flac", "audio/x-flac": ".flac",
        "audio/aiff": ".aiff", "audio/x-aiff": ".aiff", "audio/ogg": ".ogg"}


def is_audius_url(url: str) -> bool:
    host = (urlparse(url.strip()).hostname or "").lower()
    return host == "audius.co" or host.endswith(".audius.co")


class AudiusSource:
    name = "audius"

    def __init__(self, client_id: str | None = None):
        # Signature matches the other sources; read-only calls need no key.
        self._session = requests.Session()
        self._session.headers["User-Agent"] = USER_AGENT

    def configured(self) -> bool:
        return True

    # ------------------------------------------------------------------ api

    def _get(self, path: str, **params) -> dict:
        params["app_name"] = APP_NAME
        try:
            # /resolve answers with a 302 to the canonical resource; requests follows it.
            resp = self._session.get(f"{API_ROOT}{path}", params=params, timeout=TIMEOUT)
        except requests.RequestException as e:
            raise SourceError(f"Couldn't reach Audius: {e}") from e
        if resp.status_code == 404:
            raise SourceError("Audius doesn't know that link — is the playlist public?")
        try:
            resp.raise_for_status()
            return resp.json()
        except requests.HTTPError as e:
            raise SourceError(f"Audius request failed: {e}") from e
        except ValueError as e:
            raise SourceError("Audius returned a non-JSON response") from e

    # -------------------------------------------------------------- playlists

    def playlist(self, url: str) -> ImportedPlaylist:
        """Resolve a pasted audius.co playlist, album or track link."""
        data = self._get("/resolve", url=url.strip()).get("data")
        if isinstance(data, list):
            data = data[0] if data else None
        if not data:
            raise SourceError("Audius couldn't resolve that link")

        if "playlist_name" in data:  # playlists and albums share a shape
            tracks = self._get(f"/playlists/{data['id']}/tracks").get("data") or []
            user = data.get("user") or {}
            return ImportedPlaylist(
                title=data.get("playlist_name") or "Audius playlist",
                source=self.name, url=url.strip(), owner=user.get("name"),
                image=(data.get("artwork") or {}).get("480x480"),
                tracks=[self._to_track(t) for t in tracks])
        if "title" in data and "duration" in data:  # a single track
            t = self._to_track(data)
            return ImportedPlaylist(title=t.name, source=self.name, url=url.strip(),
                                    owner=t.artist, image=t.image, tracks=[t])
        raise SourceError("That's an artist page — paste one of their playlists or albums.")

    def search(self, query: str = "", *, limit: int = 12, **_ignored) -> list[RemoteTrack]:
        rows = self._get("/tracks/search", query=query or "house", limit=min(limit * 4, 100)).get("data") or []
        return [t for t in (self._to_track(r) for r in rows) if t.downloadable][:limit]

    @staticmethod
    def _to_track(row: dict) -> RemoteTrack:
        user = row.get("user") or {}
        tid = str(row.get("id", ""))
        reason = None
        if row.get("is_delete") or row.get("is_available") is False:
            reason = "removed from Audius"
        elif row.get("is_download_gated"):
            reason = "the artist gates downloads behind a follow or purchase"
        elif not row.get("is_downloadable"):
            reason = "the artist hasn't enabled downloads"
        return RemoteTrack(
            source="audius",
            id=tid,
            name=row.get("title") or "Untitled",
            artist=user.get("name") or user.get("handle") or "Unknown artist",
            duration=float(row.get("duration") or 0.0),
            # No licence chosen on Audius means the legal default.
            license_name=row.get("license") or "All rights reserved",
            page_url=f"https://audius.co{row['permalink']}" if row.get("permalink") else None,
            image=(row.get("artwork") or {}).get("480x480"),
            tags=[t for t in (row.get("genre"), row.get("mood")) if t],
            stream_url=f"{API_ROOT}/tracks/{tid}/stream?app_name={APP_NAME}",
            download_url=None if reason else f"{API_ROOT}/tracks/{tid}/download?app_name={APP_NAME}",
            downloadable=reason is None,
            unavailable_reason=reason,
        )

    # ---------------------------------------------------------------- download

    def download(self, track: RemoteTrack, dest_dir: Path) -> Path:
        if not track.downloadable or not track.download_url:
            raise SourceError(f"{track.label}: {track.unavailable_reason or 'not downloadable'}")
        dest_dir.mkdir(parents=True, exist_ok=True)
        # The artist may have uploaded WAV or FLAC, so the extension comes from the response.
        for ext in set(_EXT.values()):
            existing = dest_dir / track.filename(ext)
            if existing.exists() and existing.stat().st_size > 0:
                return existing

        tmp = dest_dir / track.filename(".part")
        try:
            with self._session.get(track.download_url, stream=True, timeout=TIMEOUT,
                                   allow_redirects=True) as r:
                if r.status_code == 404:
                    raise SourceError(f"{track.label}: Audius refused the download")
                r.raise_for_status()
                ctype = r.headers.get("Content-Type", "").split(";")[0].strip().lower()
                ext = _EXT.get(ctype)
                if ext is None:
                    raise SourceError(f"{track.label}: expected audio, got {ctype or 'nothing'}")
                with tmp.open("wb") as fh:
                    for chunk in r.iter_content(chunk_size=1 << 16):
                        fh.write(chunk)
        except requests.RequestException as e:
            tmp.unlink(missing_ok=True)
            raise SourceError(f"Could not download {track.label}: {e}") from e
        except SourceError:
            tmp.unlink(missing_ok=True)
            raise

        if tmp.stat().st_size < 10_000:
            tmp.unlink(missing_ok=True)
            raise SourceError(f"{track.label} downloaded empty")
        dest = dest_dir / track.filename(ext)
        tmp.replace(dest)
        return dest
