"""Remote music catalogs the app can pull full-length tracks from."""

from .archive_org import ArchiveOrgSource
from .base import MusicSource, RemoteTrack, SourceError, cc_license_name
from .jamendo import JamendoSource

__all__ = ["MusicSource", "RemoteTrack", "SourceError", "cc_license_name",
           "JamendoSource", "ArchiveOrgSource", "SOURCES", "get_source"]

#: label shown in the UI -> (class, needs a credential?)
SOURCES = {
    "Internet Archive": (ArchiveOrgSource, False),
    "Jamendo": (JamendoSource, True),
}


def get_source(name: str = "Internet Archive", **kwargs) -> MusicSource:
    entry = SOURCES.get(name)
    if entry is None:
        raise SourceError(f"Unknown music source: {name}")
    return entry[0](**kwargs)
