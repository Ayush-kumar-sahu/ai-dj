"""The "Build a set" tab: bring a playlist link or a folder of songs, get a mixed set.

Flow: import (link or upload) → a saved set → "Arrange & mix" starts a background job
(sets.start_job) → this tab polls it → the finished mix plays in the live player with
a cut sheet showing exactly where every transition happens.
"""

from __future__ import annotations

import html
import re
import time
from pathlib import Path

import streamlit as st

from .. import sets
from ..arrange import DEFAULT_ANALYSIS_SECONDS, is_analyzed
from ..render import load_tracklist
from ..sources import credits, playlists
from ..sources.base import ImportedPlaylist, SourceError, allows_remix, tidy_title
from . import components as ui
from . import fx
from .player import live_player

SOURCE_LABEL = {"audius": "Audius", "jamendo": "Jamendo", "archive": "Internet Archive",
                "upload": "Uploaded"}
STAGE_LABEL = {"starting": "Warming up the decks", "analyzing": "Listening to your tracks",
               "sequencing": "Reading the room", "rendering": "Mixing", "encoding": "Pressing the record",
               "done": "Done"}
#: Rotating banter while a stage runs — every line says something true about the work.
STAGE_LINES = {
    "analyzing": ["finding the downbeats", "splitting drums, bass, vocals and the rest",
                  "hunting for the intro and the outro", "working out the key", "counting bars"],
    "sequencing": ["lining up tempos so every step is small"],
    "rendering": ["riding the faders", "swapping basslines on the downbeat", "beatmatching the blends"],
}
AUDIO_TYPES = ["mp3", "wav", "flac", "aiff", "m4a", "ogg"]
#: Confetti and the toast only fire for a mix that finished this recently (seconds).
CELEBRATE_WITHIN = 300
_UNSAFE_NAME = re.compile(r"[^\w\-. ()\[\]&,']+")


def _mins(seconds: float) -> str:
    m = round(seconds / 60)
    return "under a minute" if m < 1 else ("about a minute" if m == 1 else f"about {m} min")


def _clock(seconds: float | None) -> str:
    s = max(0, int(seconds or 0))
    return f"{s // 60}:{s % 60:02d}"


# ------------------------------------------------------------------ the tab


def render_tab(songs_dir: Path, jamendo_id: str) -> None:
    st.markdown("### 🪩 Build a set")
    st.caption("Hand me a playlist or a stack of songs. I'll listen to every track, keep the ones "
               "that groove together, line them up in the smoothest order and blend each one "
               "right on the beat.")

    mode = st.segmented_control("Bring your music", ["🔗  Playlist link", "⬆️  Upload songs"],
                                default="🔗  Playlist link", key="set_mode",
                                label_visibility="collapsed") or "🔗  Playlist link"
    if "Playlist" in mode:
        _link_panel(songs_dir, jamendo_id)
    else:
        _upload_panel(songs_dir)

    st.divider()
    _sets_panel(songs_dir)


# ------------------------------------------------------------ import a link


def _link_panel(songs_dir: Path, jamendo_id: str) -> None:
    with st.container(border=True):
        c1, c2 = st.columns([4, 1])
        link = c1.text_input("Playlist link", key="set_link", label_visibility="collapsed",
                             placeholder="audius.co/…/playlist/…  ·  jamendo.com/playlist/…  ·  "
                                         "archive.org/details/…")
        look = c2.button("🔎 Dig it up", type="primary", width="stretch")
        st.caption("Works with **Audius**, **Jamendo** and **Internet Archive** playlists and "
                   "albums. Spotify, Apple Music and YouTube can't be mixed — they never give "
                   "other apps the audio.")
    if look:
        try:
            with st.spinner("Flipping through the crates…"):
                st.session_state.imported = playlists.resolve(link, jamendo_id)
        except SourceError as e:
            st.session_state.imported = None
            st.error(str(e))
    imported: ImportedPlaylist | None = st.session_state.get("imported")
    if imported:
        _import_preview(imported, songs_dir, jamendo_id)


def _import_preview(pl: ImportedPlaylist, songs_dir: Path, jamendo_id: str) -> None:
    ok = pl.importable
    publishable = [t for t in ok if allows_remix(t)]
    have = {p.name for p in songs_dir.iterdir()}

    with st.container(border=True):
        art, info = st.columns([1, 5])
        if pl.image:
            art.image(pl.image, width="stretch")
        info.markdown(f'<div class="card-title">{html.escape(pl.title)}</div>'
                      f'<div class="card-sub">{html.escape(pl.owner or "")} · '
                      f'{SOURCE_LABEL.get(pl.source, pl.source)}</div>', unsafe_allow_html=True)
        info.markdown(ui.chips([
            ui.chip("", f"{len(pl.tracks)} tracks", "chip-muted"),
            ui.chip("", f"{len(ok)} can be imported", "chip-good" if ok else "chip-bad"),
            ui.chip("", f"{len(publishable)} licensed for remixing",
                    "chip-good" if publishable else "chip-ok"),
        ]), unsafe_allow_html=True)

        rows = []
        for t in pl.tracks:
            title = html.escape(tidy_title(t.artist, t.name))
            status = ("✓" if t.downloadable else "✕")
            badges = []
            if t.downloadable:
                badges.append(ui.link_chip(t.license_name or "no licence stated", t.license_url,
                                           "chip-key" if allows_remix(t) else "chip-ok"))
                if any(name.startswith(t.filename("")) for name in have):
                    badges.append(ui.chip("", "in library", "chip-muted"))
            else:
                badges.append(ui.chip("", t.unavailable_reason or "not downloadable", "chip-bad"))
            rows.append(f'<tr class="{"" if t.downloadable else "off"}"><td class="st">{status}</td>'
                        f'<td><b>{title}</b><br><span>{html.escape(t.artist)}</span></td>'
                        f'<td class="tm">{ui.fmt_duration(t.duration)}</td>'
                        f'<td class="bd">{"".join(badges)}</td></tr>')
        st.markdown(f'<table class="imp">{"".join(rows)}</table>', unsafe_allow_html=True)

        if not ok:
            st.warning("No luck — none of these artists allow downloads, so I can't mix them. "
                       "Try another playlist, or upload files you own.")
            return
        if len(ok) < 2:
            st.info("Only one track here can be downloaded — a set needs at least two.")
            return
        if len(publishable) < len(ok):
            st.caption(f"{len(ok) - len(publishable)} of these aren't licensed for remixing: "
                       "fine for listening to your mix, but don't publish it.")

        c1, c2 = st.columns([3, 2])
        name = c1.text_input("Set name", value=pl.title, key="import_name")
        if c2.button(f"📦 Add {len(ok)} tracks to the crate", type="primary", width="stretch"):
            _download_set(pl, ok, name, songs_dir, jamendo_id)


def _download_set(pl: ImportedPlaylist, tracks: list, name: str, songs_dir: Path,
                  jamendo_id: str) -> None:
    bar = st.progress(0.0, text="Loading the crate…")
    names, failed = [], []
    for i, t in enumerate(tracks):
        bar.progress(i / len(tracks), text=f"📦 {i + 1}/{len(tracks)} · {t.name}")
        try:
            path = playlists.source_for(t, jamendo_id).download(t, songs_dir)
        except SourceError as e:
            failed.append(f"{t.label}: {e}")
            continue
        credits.record(t, path)
        names.append(path.name)
    bar.empty()
    if len(names) < 2:
        st.error("Couldn't download enough tracks to make a set:\n\n" + "\n".join(failed))
        return
    new = sets.create_set(name, pl.source, names, source_url=pl.url)
    st.session_state.selected_set = new.id
    st.session_state.imported = None
    if failed:
        st.session_state.import_note = f"{len(failed)} track(s) failed to download."
    st.rerun()


# ------------------------------------------------------------------ uploads


def _upload_panel(songs_dir: Path) -> None:
    nonce = st.session_state.setdefault("upload_nonce", 0)
    with st.container(border=True):
        files = st.file_uploader("Drop your tunes here 🎶", type=AUDIO_TYPES,
                                 accept_multiple_files=True, key=f"set_upload_{nonce}")
        c1, c2 = st.columns([3, 2])
        name = c1.text_input("Set name", value="My set", key="upload_name")
        n = len(files or [])
        go = c2.button(f"🎚️ Make a set from {n} songs" if n else "🎚️ Make a set", type="primary",
                       width="stretch", disabled=n < 2)
        st.caption("Files stay on this computer. Mixes of music you don't hold the rights to "
                   "are for personal listening.")
    if go:
        names = []
        for up in files:
            safe = _UNSAFE_NAME.sub("_", Path(up.name).name).strip() or "track"
            if Path(safe).suffix.lower().lstrip(".") not in AUDIO_TYPES:
                continue
            dest = songs_dir / safe
            if not dest.exists():
                dest.write_bytes(up.getbuffer())
            names.append(dest.name)
        new = sets.create_set(name, "upload", names)
        st.session_state.selected_set = new.id
        st.session_state.upload_nonce = nonce + 1  # clears the uploader
        st.rerun()


# --------------------------------------------------------------------- sets


@st.fragment(run_every=2)
def _job_progress(set_id: str) -> None:
    """Polls the background job every 2 s; refreshes the page when it ends."""
    status = sets.read_status(set_id)
    if status.state != "running":
        st.rerun(scope="app")
        return
    d = status.detail or {}
    text = STAGE_LABEL.get(status.stage, status.stage.title())
    lines = STAGE_LINES.get(status.stage)
    if lines:
        text += f" — {lines[int(time.time() // 4) % len(lines)]}"
    if status.stage == "analyzing" and d:
        text += f" · {d.get('index')}/{d.get('total')} · {d.get('track', '')}"
        if d.get("fresh") and d.get("eta_seconds"):
            text += f" · {_mins(d['eta_seconds'])} left"
    elif status.stage == "rendering" and d.get("step"):
        text += f" · {d['step']}"
    st.progress(min(1.0, max(0.0, status.progress)), text=text)
    c1, c2 = st.columns([4, 1])
    c1.caption(f"Running in the background for {_clock(time.time() - (status.started_at or time.time()))}"
               " — you can refresh or leave this page.")
    if c2.button("Cancel", key=f"cancel-{set_id}", width="stretch"):
        sets.cancel_job(set_id)
        st.rerun(scope="app")


def _sets_panel(songs_dir: Path) -> None:
    st.markdown("### 🎧 Your sets")
    all_sets = sets.list_sets()
    if not all_sets:
        st.info("No sets yet — paste a playlist or drop some songs above and let's go. 🪩")
        return
    if note := st.session_state.pop("import_note", None):
        st.warning(note)

    by_id = {s.id: s for s in all_sets}
    ids = list(by_id)
    # Drive the dropdown through session state rather than `index=`: Streamlit doesn't
    # re-apply `index` to a keyed widget whose options changed (a new set was just
    # added), so the label and the returned value can drift apart.
    wanted = st.session_state.get("selected_set")
    st.session_state.set_pick = wanted if wanted in ids else ids[0]

    def _picked() -> None:
        st.session_state.selected_set = st.session_state.set_pick

    choice = st.selectbox(
        "Set", ids, key="set_pick", on_change=_picked, label_visibility="collapsed",
        format_func=lambda i: f"{by_id[i].name}  ·  {len(by_id[i].tracks)} tracks  ·  "
                              f"{SOURCE_LABEL.get(by_id[i].source, by_id[i].source)}  ·  "
                              f"{by_id[i].created_at}")
    st.session_state.selected_set = choice
    track_set = by_id[choice]
    status = sets.read_status(choice)

    present = [n for n in track_set.tracks if (songs_dir / n).exists()]
    fresh = [n for n in present if not is_analyzed(songs_dir / n)]

    if status.state == "running":
        _job_progress(choice)
    else:
        busy = sets.running_job()
        c1, c2, c3 = st.columns([2.2, 2.4, 1])
        label = "🔁 Remix it" if status.state == "done" else "🔥 Mix my set"
        if c1.button(label, type="primary", width="stretch", key=f"go-{choice}",
                     disabled=bool(busy) or len(present) < 2):
            try:
                sets.start_job(choice)
            except RuntimeError as e:
                st.error(str(e))
            else:
                st.rerun()
        if busy:
            c2.caption("Another set is on the decks — one at a time, so analysis has the memory.")
        elif fresh:
            c2.caption(f"{len(fresh)} of {len(present)} tracks need analysis first · "
                       f"{_mins(len(fresh) * DEFAULT_ANALYSIS_SECONDS)}")
        else:
            c2.caption(f"All {len(present)} tracks are warmed up — mixing takes about a minute.")
        if c3.button("🗑️", key=f"del-{choice}", width="stretch",
                     help="Removes the set and its mix. The songs stay in your library."):
            sets.delete_set(choice)
            st.session_state.selected_set = None
            st.rerun()

        if status.state == "failed":
            st.error(f"The needle skipped: {status.error}")
            with st.expander("Job log"):
                try:
                    st.code(sets.log_path(choice).read_text()[-4000:], language=None)
                except FileNotFoundError:
                    st.caption("No log.")
        elif status.state == "cancelled":
            st.info("Cancelled. Already-analyzed tracks are kept, so a re-run picks up quickly.")
        elif status.state == "done" and status.result:
            _set_result(choice, status.result, status.updated_at)

    with st.expander(f"Tracks in this set ({len(present)})"):
        for n in track_set.tracks:
            mark = "✓" if n in present and n not in fresh else ("…" if n in present else "✕ missing")
            st.markdown(f"`{mark}` {html.escape(ui.display_name(n))}")


def _set_result(set_id: str, result: dict, finished_at: float | None) -> None:
    mp3 = Path(result.get("mp3") or "")
    mix = Path(result.get("mix") or "")
    if not mp3.is_file():
        st.warning("The mix file is missing — run it again.")
        return
    tracklist = load_tracklist(mix)
    burst = f"{set_id}-{int(finished_at or 0)}"
    # Celebrate a mix that just finished — not an old one opened in a new session.
    fresh = finished_at is not None and time.time() - finished_at < CELEBRATE_WITHIN
    if fresh:
        fx.confetti(burst)  # once per finished mix per tab, not on every rerun
    if fresh and not st.session_state.get(f"toasted-{burst}"):
        st.session_state[f"toasted-{burst}"] = True
        n = len(result.get("queue", []))
        mins = (tracklist or {}).get("duration", 0) / 60
        st.toast(f"Your set is ready — {n} tracks, {mins:.0f} minutes. Press play!", icon="🎉")
    live_player(mp3, tracklist, key=f"set-{set_id}")

    if tracklist and len(tracklist.get("tracks", [])) > 1:
        with st.expander("✂️  Cut sheet — exactly where every blend lands", expanded=True):
            st.markdown(_cut_sheet(tracklist), unsafe_allow_html=True)
            st.caption("Each blend starts on a downbeat. Drums and pads crossfade across it; "
                       "bass and vocals hand over at once at the swap, so two basslines never "
                       "clash — that's where you hear the change of track.")

    notes = []
    for s in result.get("sitting_out", []):
        notes.append(f"**{html.escape(ui.display_name(s['track']))}** sat out — {s['reason']}.")
    for f in result.get("failed", []):
        notes.append(f"**{html.escape(ui.display_name(f['track']))}** — {f['reason']}.")
    for m in result.get("missing", []):
        notes.append(f"**{html.escape(ui.display_name(m))}** is no longer in the library.")
    if notes:
        st.markdown("\n".join(f"- {n}" for n in notes))

    st.download_button("⬇️ Download MP3", data=lambda p=mp3: p.read_bytes(),
                       file_name=f"{set_id}.mp3", mime="audio/mpeg", key=f"dl-{set_id}")
    st.caption(f"Lossless WAV master: `{mix}`")


def _cut_sheet(tracklist: dict) -> str:
    cues = tracklist["tracks"]

    def name(cue: dict) -> str:
        credit = cue.get("credit") or {}
        if credit.get("artist") and credit.get("title"):
            return tidy_title(credit["artist"], credit["title"])
        return cue.get("title", "")

    rows = []
    for a, b in zip(cues, cues[1:]):
        tempo = (f"{a['bpm']:.0f} → {b['bpm']:.0f}" if round(a["bpm"]) != round(b["bpm"])
                 else f"{b['bpm']:.0f}")
        rows.append(
            f"<tr><td class='n'>{a['number']}→{b['number']}</td>"
            f"<td><b>{html.escape(name(a))}</b> → <b>{html.escape(name(b))}</b></td>"
            f"<td>out at {_clock(a.get('exits_from'))}</td>"
            f"<td>in from {_clock(b.get('enters_from'))}</td>"
            f"<td>{b.get('blend_bars', '–')} bars</td>"
            f"<td>{tempo} BPM</td>"
            f"<td>{html.escape(a.get('camelot') or '?')} → {html.escape(b.get('camelot') or '?')}</td>"
            f"<td class='sw'>{_clock(b.get('swap'))}</td></tr>")
    head = ("<tr><th></th><th>Transition</th><th>Mix out of A</th><th>Into B</th>"
            "<th>Blend</th><th>Tempo</th><th>Key</th><th>Change at</th></tr>")
    return f"<table class='cuts'>{head}{''.join(rows)}</table>"
