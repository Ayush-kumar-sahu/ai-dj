"""Saved sets — a named group of library tracks — and the background job that mixes one.

Mixing a fresh set means analyzing every track (~3 min each on CPU), far longer than a
browser tab should be trusted to stay open. So the work runs as its own process
(`aidj arrange <set>`), reporting into data/sets/<id>/status.json; the web app only
starts it, polls that file and can cancel it. Refreshing or closing the page is fine.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]
SETS_DIR = ROOT / "data" / "sets"
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")

JobState = Literal["idle", "running", "done", "failed", "cancelled"]


class TrackSet(BaseModel):
    id: str
    name: str
    source: str                      # "upload" | "audius" | "jamendo" | "archive"
    source_url: str | None = None
    created_at: str
    tracks: list[str]                # library filenames, in the order they were added


class JobStatus(BaseModel):
    state: JobState = "idle"
    pid: int | None = None
    stage: str = ""
    progress: float = 0.0
    detail: dict = Field(default_factory=dict)
    started_at: float | None = None
    updated_at: float | None = None
    error: str | None = None
    result: dict | None = None


# ------------------------------------------------------------------ storage


def set_dir(set_id: str) -> Path:
    """The set's folder. Ids are validated so a crafted one can't escape SETS_DIR."""
    if not _ID.match(set_id or ""):
        raise ValueError(f"invalid set id: {set_id!r}")
    return SETS_DIR / set_id


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return (s or "set")[:40]


def _write_json(path: Path, payload: dict) -> None:
    """Atomic write: the web app polls these files while the job rewrites them."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    tmp.replace(path)


def create_set(name: str, source: str, tracks: list[str],
               source_url: str | None = None) -> TrackSet:
    s = TrackSet(id=f"{_slug(name)}-{secrets.token_hex(3)}", name=name.strip() or "Untitled set",
                 source=source, source_url=source_url,
                 created_at=time.strftime("%Y-%m-%d %H:%M"), tracks=list(dict.fromkeys(tracks)))
    _write_json(set_dir(s.id) / "set.json", s.model_dump())
    return s


def load_set(set_id: str) -> TrackSet | None:
    try:
        return TrackSet.model_validate_json((set_dir(set_id) / "set.json").read_text())
    except (FileNotFoundError, ValueError):
        return None


def list_sets() -> list[TrackSet]:
    if not SETS_DIR.exists():
        return []
    found = [load_set(d.name) for d in SETS_DIR.iterdir() if d.is_dir() and _ID.match(d.name)]
    return sorted([s for s in found if s], key=lambda s: s.created_at, reverse=True)


def delete_set(set_id: str) -> None:
    """Remove the set and its mix. The songs stay in the library."""
    cancel_job(set_id)
    d = set_dir(set_id)
    if d.exists() and d.resolve().parent == SETS_DIR.resolve():
        shutil.rmtree(d)


def mix_path(set_id: str) -> Path:
    return set_dir(set_id) / "mix.wav"


def log_path(set_id: str) -> Path:
    return set_dir(set_id) / "job.log"


# --------------------------------------------------------------------- jobs


def _alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        # Reap it if it's our own finished child — a zombie still "exists" to kill(0).
        done, _ = os.waitpid(pid, os.WNOHANG)
        if done == pid:
            return False
    except ChildProcessError:
        pass  # not our child (started by an earlier server process)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def read_status(set_id: str) -> JobStatus:
    try:
        status = JobStatus.model_validate_json((set_dir(set_id) / "status.json").read_text())
    except (FileNotFoundError, ValueError):
        return JobStatus()
    if status.state == "running" and not _alive(status.pid):
        status.state, status.error = "failed", "The job stopped unexpectedly — see the log."
        write_status(set_id, status)
    return status


def write_status(set_id: str, status: JobStatus) -> None:
    status.updated_at = time.time()
    _write_json(set_dir(set_id) / "status.json", status.model_dump())


def running_job() -> str | None:
    """Id of the set currently being mixed, if any. One at a time: Demucs wants the RAM."""
    for s in list_sets():
        if read_status(s.id).state == "running":
            return s.id
    return None


def start_job(set_id: str) -> JobStatus:
    if load_set(set_id) is None:
        raise ValueError(f"no set {set_id}")
    busy = running_job()
    if busy:
        raise RuntimeError(f"Another set is being mixed ({busy}). Wait for it or cancel it.")
    log = log_path(set_id).open("w")
    proc = subprocess.Popen(
        [sys.executable, "-m", "ai_dj.cli", "arrange", set_id],
        cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        start_new_session=True,  # its own process group, so cancel also stops Demucs
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    log.close()
    status = JobStatus(state="running", pid=proc.pid, stage="starting",
                       started_at=time.time())
    write_status(set_id, status)
    return status


def _signal_group(pid: int | None, sig: int) -> None:
    try:
        os.killpg(pid, sig)  # the job's own process group: the job plus Demucs
    except (ProcessLookupError, PermissionError, TypeError):
        pass


def cancel_job(set_id: str, grace: float = 5.0) -> None:
    status = read_status(set_id)
    if status.state != "running":
        return
    # Mark it first: a job about to report progress sees this and stops quietly.
    status.state, status.error = "cancelled", None
    write_status(set_id, status)
    _signal_group(status.pid, signal.SIGTERM)
    deadline = time.time() + grace
    while _alive(status.pid) and time.time() < deadline:  # _alive also reaps it
        time.sleep(0.1)
    if _alive(status.pid):
        _signal_group(status.pid, signal.SIGKILL)
        time.sleep(0.2)
        _alive(status.pid)
    write_status(set_id, status)  # in case it wrote progress between our reads
