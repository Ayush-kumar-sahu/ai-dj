"""Turn a pasted playlist or album link from an open music platform into tracks.

Only platforms that hand apps the actual audio can feed a DJ mix. The big streaming
services never do (their audio is DRM-protected and their APIs give at most a
30-second preview), so a link from one of them gets an explanation, not an error.
"""

from __future__ import annotations

from urllib.parse import urlparse

from .archive_org import ArchiveOrgSource
from .audius import AudiusSource
from .base import ImportedPlaylist, MusicSource, RemoteTrack, SourceError
from .jamendo import JamendoSource

SUPPORTED = "Audius, Jamendo or the Internet Archive"

#: host → platform name, for links we can recognise but can't use.
UNSUPPORTED = {
    "spotify.com": "Spotify", "music.apple.com": "Apple Music", "youtube.com": "YouTube",
    "youtu.be": "YouTube", "soundcloud.com": "SoundCloud", "deezer.com": "Deezer",
    "tidal.com": "Tidal", "music.amazon.com": "Amazon Music", "bandcamp.com": "Bandcamp",
}


def normalise(url: str) -> str:
    url = url.strip()
    return url if "://" in url else f"https://{url}"


def _host_is(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def platform_of(url: str) -> str | None:
    host = (urlparse(normalise(url)).hostname or "").lower()
    if _host_is(host, "audius.co"):
        return "audius"
    if _host_is(host, "jamendo.com"):
        return "jamendo"
    if _host_is(host, "archive.org"):
        return "archive"
    return None


def resolve(url: str, jamendo_client_id: str | None = None) -> ImportedPlaylist:
    """Look up a playlist/album link. Raises SourceError with a human explanation."""
    if not url.strip():
        raise SourceError(f"Paste a playlist or album link from {SUPPORTED}.")
    url = normalise(url)
    host = (urlparse(url).hostname or "").lower()
    for domain, name in UNSUPPORTED.items():
        if _host_is(host, domain):
            extra = " If you own the files, upload them instead." if name == "Bandcamp" else ""
            raise SourceError(f"{name} doesn't let other apps download its audio, so its "
                              f"playlists can't be mixed here. Try {SUPPORTED}.{extra}")
    platform = platform_of(url)
    if platform == "audius":
        return AudiusSource().playlist(url)
    if platform == "jamendo":
        return JamendoSource(jamendo_client_id).playlist(url)
    if platform == "archive":
        return ArchiveOrgSource().item(url)
    raise SourceError(f"Paste a playlist or album link from {SUPPORTED}.")


def source_for(track: RemoteTrack, jamendo_client_id: str | None = None) -> MusicSource:
    """The catalog a track came from — downloads must go back through it."""
    if track.source == "jamendo":
        return JamendoSource(jamendo_client_id)
    if track.source == "audius":
        return AudiusSource()
    return ArchiveOrgSource()
