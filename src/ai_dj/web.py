"""Streamlit console for the AI DJ.

Run with:  streamlit run src/ai_dj/web.py
"""

from __future__ import annotations

import html
import json
import shutil
from pathlib import Path

import streamlit as st

from ai_dj import audio as audio_mod
from ai_dj import cache as cache_mod
from ai_dj import compatibility, ordering, sets, waveform
from ai_dj.analysis.analyzer import analyze
from ai_dj.demo import DEMO_MIX
from ai_dj.render import load_tracklist, plan_queue, render_queue
from ai_dj.sources import SOURCES, ArchiveOrgSource, RemoteTrack, SourceError, credits, playlists
from ai_dj.sources.archive_org import DJ_SUBJECTS
from ai_dj.sources.jamendo import DJ_TAGS, ORDERS, SPEEDS, JamendoSource
from ai_dj.types import TrackAnalysis
from ai_dj.ui import components as ui
from ai_dj.ui import set_builder, theme
from ai_dj.ui.player import live_player

ROOT = Path(__file__).resolve().parents[2]
SONGS_DIR = ROOT / "data" / "songs"
OUTPUT_DIR = ROOT / "data" / "output"
CONFIG_PATH = ROOT / "data" / "config.json"
SONGS_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

SUPPORTED = {".mp3", ".wav", ".flac", ".aiff", ".m4a", ".ogg"}
AUDIO_MIME = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".flac": "audio/flac",
              ".aiff": "audio/aiff", ".m4a": "audio/mp4", ".ogg": "audio/ogg"}

st.set_page_config(page_title="AI DJ", layout="wide", page_icon="🎧",
                   initial_sidebar_state="expanded")
theme.inject()


# --------------------------------------------------------------- persistence


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_config(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


def list_library() -> list[Path]:
    return sorted([p for p in SONGS_DIR.iterdir() if p.suffix.lower() in SUPPORTED])


@st.cache_data(show_spinner=False)
def get_peaks(path: str, fingerprint: str) -> list[float]:
    """`fingerprint` is unused in the body but part of the cache key, so edits bust it.

    It must not start with an underscore — Streamlit excludes those from the key.
    """
    return waveform.peaks(Path(path))


def peaks_for(path: Path) -> list[float]:
    return get_peaks(str(path), cache_mod.file_key(path))


@st.cache_data(show_spinner=False, ttl=900)
def jamendo_search(client_id: str, **kwargs) -> list[RemoteTrack]:
    return JamendoSource(client_id).search(**kwargs)


@st.cache_data(show_spinner=False, ttl=900)
def archive_search(**kwargs) -> list[RemoteTrack]:
    return ArchiveOrgSource().search(**kwargs)


def analysed(paths: list[Path]) -> dict[str, TrackAnalysis]:
    out = {}
    for p in paths:
        a = cache_mod.load_analysis(p)
        if a is not None:
            out[p.name] = a
    return out


# ------------------------------------------------------------------ state

cfg = load_config()
disk_queue = list(cfg.get("queue", []))
if "queue" not in st.session_state:
    st.session_state.queue = list(disk_queue)
    st.session_state.queue_synced = list(disk_queue)
elif st.session_state.queue != st.session_state.queue_synced:
    # changed in this session → persist, so a browser refresh doesn't lose the set
    cfg["queue"] = list(st.session_state.queue)
    save_config(cfg)
    st.session_state.queue_synced = list(st.session_state.queue)
elif disk_queue != st.session_state.queue_synced:
    # changed on disk by someone else (e.g. `aidj demo`) → adopt it
    st.session_state.queue = list(disk_queue)
    st.session_state.queue_synced = list(disk_queue)
st.session_state.setdefault("jamendo_id", cfg.get("jamendo_client_id", ""))
st.session_state.setdefault("run_stems", True)
st.session_state.setdefault("results", [])

library = list_library()
analyses = analysed(library)


# ----------------------------------------------------------------- sidebar

with st.sidebar:
    st.markdown("### 🎛️ Booth status")

    ready = sum(1 for a in analyses.values() if a.stems_dir)
    c1, c2, c3 = st.columns(3)
    c1.metric("Crate", len(library))
    c2.metric("Analyzed", len(analyses))
    c3.metric("Ready", ready)

    st.divider()
    st.markdown("**🔌 Music source**")
    client_id = st.text_input(
        "Jamendo client ID", value=st.session_state.jamendo_id, type="password",
        help="Free key from devportal.jamendo.com. Or export JAMENDO_CLIENT_ID.",
        placeholder="paste your client_id",
    )
    st.session_state.jamendo_id = client_id
    if client_id and client_id != cfg.get("jamendo_client_id"):
        if st.button("💾 Remember on this machine", width="stretch"):
            cfg["jamendo_client_id"] = client_id
            save_config(cfg)
            st.toast("Saved to data/config.json")
    st.caption("[Get a free key →](https://devportal.jamendo.com/)")

    st.divider()
    st.markdown("**🧠 Analysis**")
    st.session_state.run_stems = st.toggle(
        "Separate stems (Demucs)", value=st.session_state.run_stems,
        help="Required to render mixes. Slow: roughly 1–3 min per track on CPU.")

    st.divider()
    with st.expander("⬆️ Upload local files"):
        uploads = st.file_uploader("Drop audio", accept_multiple_files=True,
                                    type=[s.lstrip(".") for s in SUPPORTED],
                                    label_visibility="collapsed")
        if uploads:
            for up in uploads:
                dest = SONGS_DIR / up.name
                if not dest.exists():
                    dest.write_bytes(up.getbuffer())
            st.rerun()

    if st.button("🧹 Clear analysis cache", width="stretch"):
        if cache_mod.CACHE_ROOT.exists():
            shutil.rmtree(cache_mod.CACHE_ROOT)
        st.cache_data.clear()
        st.rerun()


demo_tl = load_tracklist(DEMO_MIX)
finished = [s for s in sets.list_sets() if sets.read_status(s.id).state == "done"]
ticker = [f"● {len(library)} TRACKS IN THE CRATE", f"● {ready} MIX-READY",
          f"● {len(finished)} SET{'S' if len(finished) != 1 else ''} MIXED"]
if demo_tl:
    ticker.append(f"● DEMO SET {ui.fmt_duration(demo_tl['duration'])} · "
                  f"{len(demo_tl['tracks'])} TRACKS")
ticker += ["● BEATMATCHED ON THE DOWNBEAT", "● BASS SWAPS — NEVER TWO BASSLINES AT ONCE",
           "● AUDIUS · JAMENDO · INTERNET ARCHIVE"]
theme.hero("Drop a playlist. I'll find the outros, match the tempo and swap the bass "
           "<b>right on the downbeat</b>. 🎛️", ticker)

demo_mp3 = DEMO_MIX.with_suffix(".mp3")
if demo_mp3.exists():
    n_demo = len(demo_tl["tracks"]) if demo_tl else 0
    demo_len = f" · {ui.fmt_duration(demo_tl['duration'])}" if demo_tl else ""
    with st.expander(f"🪩  Demo set — {n_demo} tracks{demo_len} · mixed live by the AI DJ",
                     expanded=True):
        live_player(demo_mp3, demo_tl, key="demo")
        st.caption("Tracks from Internet Archive netlabels under Creative Commons licences "
                   "that permit derivatives. Credit the artists above if you share this mix.")

tab_sets, tab_discover, tab_library, tab_queue, tab_mix = st.tabs(
    ["🪩  Build a set", "🔍  Discover", "📦  Crate", "🎚️  Queue", "🎛️  Mix desk"])


# ------------------------------------------------------------- build a set

with tab_sets:
    set_builder.render_tab(SONGS_DIR, st.session_state.jamendo_id)


# ---------------------------------------------------------------- discover

with tab_discover:
    st.markdown("### 🔍 Dig for tracks")
    st.caption("Crate-digging across free catalogs that hand over full-length audio — "
               "preview anything, then pull it into your crate.")
    src_name = st.segmented_control(
        "Catalog", list(SOURCES), default="Internet Archive", key="disc_source",
        help="Internet Archive works out of the box. Jamendo has richer metadata and "
             "curation but needs a free client ID.") or "Internet Archive"
    is_jamendo = src_name == "Jamendo"
    source = JamendoSource(st.session_state.jamendo_id) if is_jamendo else ArchiveOrgSource()

    if not source.configured():
        with st.container(border=True):
            st.markdown("#### Connect Jamendo")
            st.markdown(
                "~500,000 Creative Commons tracks with **full-length downloads** and good "
                "genre metadata. Preview-clip APIs (Spotify, Deezer, iTunes) can't work for "
                "a DJ — you can't beatmatch an outro you were never given."
            )
            st.markdown(
                "1. Sign up at [devportal.jamendo.com](https://devportal.jamendo.com/) — free, instant\n"
                "2. Create an app and copy its **client ID**\n"
                "3. Paste it into the sidebar (or `export JAMENDO_CLIENT_ID=...`)"
            )
            st.caption("No key? Switch the catalog to **Internet Archive** — it needs none.")
    else:
        with st.container(border=True):
            r1c1, r1c2 = st.columns([3, 1])
            query = r1c1.text_input("Search", placeholder="artist, title, or mood…",
                                    label_visibility="collapsed")
            if is_jamendo:
                order_label = r1c2.selectbox("Sort", list(ORDERS),
                                             label_visibility="collapsed")
            else:
                r1c2.caption("Most-downloaded releases first")

            genres = DJ_TAGS if is_jamendo else DJ_SUBJECTS
            tags = st.pills("Genres", genres, selection_mode="multi",
                            default=[genres[0]], key=f"disc_tags_{src_name}")

            r2c1, r2c2, r2c3 = st.columns([2, 2, 1.4])
            if is_jamendo:
                speed = r2c1.segmented_control("Tempo feel", ["any", *SPEEDS],
                                               default="any")
            else:
                r2c1.caption("No tempo filter in this catalog — exact BPM comes from "
                             "analysis once a track is in your library.")
            length = r2c2.slider("Length (min)", 1, 12, (3, 8))
            count = r2c3.number_input("Results", 6, 36, 12, step=6)

            r3c1, r3c2 = st.columns(2)
            remixable = r3c1.toggle(
                "Remixable licences only", value=True,
                help="Keeps only Creative Commons licences that allow derivatives. A DJ "
                     "mix is a derivative work, so no-derivatives (ND) or unlicensed "
                     "tracks are ones you can't legally publish a mix of.")
            go = r3c2.button(f"🔎 Search {src_name}", type="primary", width="stretch")

        if go:
            kwargs = dict(query=query, tags=list(tags or []), limit=int(count),
                          min_duration=length[0] * 60, max_duration=length[1] * 60,
                          remixable_only=remixable)
            try:
                with st.spinner(f"Searching {src_name}…"):
                    if is_jamendo:
                        st.session_state.results = jamendo_search(
                            st.session_state.jamendo_id, order=ORDERS[order_label],
                            speed=None if speed in (None, "any") else speed, **kwargs)
                    else:
                        st.session_state.results = archive_search(**kwargs)
            except SourceError as e:
                st.error(str(e))
                st.session_state.results = []

        results: list[RemoteTrack] = st.session_state.results
        if results:
            have = {p.name for p in library}
            st.caption(f"{len(results)} downloadable tracks")

            for row_start in range(0, len(results), 3):
                cols = st.columns(3)
                for col, track in zip(cols, results[row_start:row_start + 3]):
                    with col, st.container(border=True):
                        if track.image:
                            st.image(track.image, width="stretch")
                        title = ui.tidy_title(track.artist, track.name)
                        st.markdown(f'<div class="card-title">{html.escape(title)}</div>'
                                    f'<div class="card-sub">{html.escape(track.artist)}</div>',
                                    unsafe_allow_html=True)
                        meta = [ui.chip("", ui.fmt_duration(track.duration), "chip-muted")]
                        if track.speed:
                            meta.append(ui.chip("speed", track.speed, "chip-bpm"))
                        if track.license_name:
                            meta.append(ui.link_chip(track.license_name, track.license_url,
                                                     "chip-key"))
                        st.markdown(ui.chips(meta), unsafe_allow_html=True)

                        if track.stream_url:
                            st.audio(track.stream_url, format="audio/mpeg")

                        if track.filename() in have:
                            st.success("In library", icon=":material/check_circle:")
                        elif st.button("⬇️ Add to library", key=f"dl-{track.source}-{track.id}",
                                       width="stretch"):
                            try:
                                with st.spinner(f"Downloading {title}…"):
                                    path = playlists.source_for(track, st.session_state.jamendo_id).download(
                                        track, SONGS_DIR)
                                credits.record(track, path)
                                st.rerun()
                            except SourceError as e:
                                st.error(str(e))
        elif go:
            st.info("Nothing matched. Try fewer genre pills or a wider length range.")


# ----------------------------------------------------------------- library

with tab_library:
    if not library:
        st.info("Your crate is empty — dig up some tracks in **Discover**, or drop files in "
                "the sidebar. 📦")
    else:
        head1, head2 = st.columns([3, 1])
        pending = [p for p in library
                   if p.name not in analyses
                   or (st.session_state.run_stems and not analyses[p.name].stems_dir)]
        head1.markdown(f"**{len(library)} tracks** · {len(pending)} need analysis")

        if pending and head2.button(f"⚡ Warm up all ({len(pending)})", type="primary",
                                    width="stretch"):
            bar = st.progress(0.0, text="Starting…")
            for i, p in enumerate(pending):
                bar.progress(i / len(pending), text=f"Analyzing {p.stem} …")
                try:
                    analyze(p, run_stems=st.session_state.run_stems)
                except Exception as e:  # one bad file shouldn't halt the batch
                    st.warning(f"{p.name}: {e}")
            bar.progress(1.0, text="Done")
            st.rerun()

        st.markdown(ui.section_legend(), unsafe_allow_html=True)
        st.write("")

        for p in library:
            a = analyses.get(p.name)
            with st.container(border=True):
                left, right = st.columns([1.5, 2.5])

                with left:
                    st.markdown(f'<div class="title-row">{ui.vinyl_badge(p.name)}'
                                f'<div class="card-title">{html.escape(ui.display_name(p.name))}'
                                '</div></div>',
                                unsafe_allow_html=True)
                    if a:
                        st.markdown(ui.track_chips(a), unsafe_allow_html=True)
                    else:
                        st.markdown(ui.chip("not analyzed", None, "chip-bad"),
                                    unsafe_allow_html=True)

                    b1, b2, b3 = st.columns(3)
                    if b1.button("Analyze", key=f"an-{p.name}", width="stretch"):
                        with st.spinner(f"Analyzing {p.stem} …"):
                            analyze(p, run_stems=st.session_state.run_stems, force=True)
                        st.rerun()
                    in_queue = p.name in st.session_state.queue
                    if b2.button("Queued ✓" if in_queue else "＋ Queue",
                                 key=f"q-{p.name}", disabled=in_queue, width="stretch"):
                        st.session_state.queue.append(p.name)
                        st.rerun()
                    if b3.button("Delete", key=f"rm-{p.name}", width="stretch"):
                        p.unlink(missing_ok=True)
                        credits.forget(p)
                        if in_queue:
                            st.session_state.queue.remove(p.name)
                        st.rerun()

                with right:
                    if a:
                        st.plotly_chart(ui.waveform_fig(a, peaks_for(p)),
                                        width="stretch", config=theme.PLOTLY_CONFIG,
                                        key=f"wf-{p.name}")
                    else:
                        st.caption("Analyze to see structure, tempo and key.")
                        st.audio(str(p), format=AUDIO_MIME.get(p.suffix.lower(), "audio/wav"))


# ------------------------------------------------------------------- queue

with tab_queue:
    queue: list[str] = [n for n in st.session_state.queue if (SONGS_DIR / n).exists()]
    st.session_state.queue = queue

    addable = [p.name for p in library if p.name not in queue]
    a1, a2, a3 = st.columns([3, 1, 1])
    pick = a1.selectbox("Add a track", [""] + addable, label_visibility="collapsed",
                        format_func=lambda n: ui.display_name(n) if n else "Add a track…")
    if a2.button("＋ Add", width="stretch", disabled=not pick):
        st.session_state.queue.append(pick)
        st.rerun()
    if a3.button("Clear", width="stretch", disabled=not queue):
        st.session_state.queue = []
        st.rerun()

    if not queue:
        st.info("The queue's empty — add two or more tracks and I'll plan the blends. 🎚️")
    else:
        q_tracks = [analyses.get(n) for n in queue]
        fully_analysed = all(t is not None for t in q_tracks)

        if fully_analysed and len(queue) >= 3:
            o1, o2 = st.columns([1, 3])
            if o1.button("🪄 Auto-order", type="primary", width="stretch",
                         help="Re-sequence for the smoothest run of transitions"):
                with st.spinner("Solving running order…"):
                    idx, cost = ordering.optimal_order(q_tracks)  # type: ignore[arg-type]
                before = ordering.path_cost(list(range(len(queue))),
                                            ordering.cost_matrix(q_tracks))  # type: ignore[arg-type]
                st.session_state.queue = [queue[i] for i in idx]
                st.toast(f"Reshuffled — transition cost {before:.1f} → {cost:.1f}", icon="🪄")
                st.rerun()
            o2.caption("Let me shuffle these into the smoothest run of blends — I weigh "
                       "tempo, key and energy for every possible pairing.")
        elif not fully_analysed:
            st.warning("Some queued tracks aren't analyzed yet — "
                       "compatibility and auto-ordering need that first.")

        st.write("")
        for i, name in enumerate(queue):
            a = analyses.get(name)
            with st.container(border=True):
                c_num, c_body, c_up, c_dn, c_rm = st.columns([0.5, 6, 0.7, 0.7, 0.7])
                c_num.markdown(f'<div class="card-num">{i + 1:02d}</div>',
                               unsafe_allow_html=True)
                # names come from catalog metadata anyone can upload: escape before HTML
                c_body.markdown(f'<div class="title-row">{ui.vinyl_badge(name)}'
                                f'<div class="card-title">{html.escape(ui.display_name(name))}'
                                '</div></div>', unsafe_allow_html=True)
                if a:
                    c_body.markdown(ui.track_chips(a), unsafe_allow_html=True)
                else:
                    c_body.markdown(ui.chip("not analyzed", None, "chip-bad"),
                                    unsafe_allow_html=True)

                if c_up.button("↑", key=f"up-{i}", disabled=i == 0, width="stretch"):
                    queue[i - 1], queue[i] = queue[i], queue[i - 1]
                    st.session_state.queue = queue
                    st.rerun()
                if c_dn.button("↓", key=f"dn-{i}", disabled=i == len(queue) - 1,
                               width="stretch"):
                    queue[i], queue[i + 1] = queue[i + 1], queue[i]
                    st.session_state.queue = queue
                    st.rerun()
                if c_rm.button("✕", key=f"qrm-{i}", width="stretch"):
                    st.session_state.queue.pop(i)
                    st.rerun()

            # the rail between this track and the next shows how well they mix
            if i < len(queue) - 1:
                nxt = analyses.get(queue[i + 1])
                if a and nxt:
                    s, breakdown = compatibility.score(a, nxt)
                    label, css = ui.compat_label(s)
                    bits = [ui.chip("", label, css),
                            ui.chip("ΔBPM", f"{abs(a.bpm - nxt.bpm) / a.bpm * 100:.1f}%",
                                    "chip-muted"),
                            ui.chip("", f"{a.camelot or '?'} → {nxt.camelot or '?'}",
                                    "chip-key")]
                    st.markdown(f'<div class="link-rail">↓ {"".join(bits)}</div>',
                                unsafe_allow_html=True)
                else:
                    st.markdown('<div class="link-rail">↓ analyze both to score this '
                                'transition</div>', unsafe_allow_html=True)


# --------------------------------------------------------------------- mix

with tab_mix:
    queue = st.session_state.queue
    queue_paths = [SONGS_DIR / n for n in queue]

    if len(queue_paths) < 2:
        st.info("Line up at least two tracks in the **Queue** first, then come back to "
                "the desk. 🎛️")
    else:
        tracks: list[TrackAnalysis] = []
        blocked: list[str] = []
        for p in queue_paths:
            a = analyses.get(p.name)
            if a is None:
                blocked.append(f"{ui.display_name(p.name)} — not analyzed")
            elif not a.stems_dir:
                blocked.append(f"{ui.display_name(p.name)} — no stems")
            else:
                tracks.append(a)

        if blocked:
            st.warning("Rendering needs stems for every track:\n\n"
                       + "\n".join(f"- {b}" for b in blocked))
            if st.button("⚡ Fix: analyze these with stems", type="primary"):
                bar = st.progress(0.0)
                for i, p in enumerate(queue_paths):
                    bar.progress(i / len(queue_paths), text=f"Analyzing {p.stem} …")
                    analyze(p, run_stems=True)
                st.rerun()

        if tracks and len(tracks) == len(queue_paths):
            # Same chained planner the renderer uses, so this preview is what you'll hear.
            try:
                plans = list(zip(tracks, tracks[1:], plan_queue(tracks)))
            except ValueError as e:
                plans = [(a, b, str(e)) for a, b in zip(tracks, tracks[1:])]

            total_bars = sum(p.transition_bars for _, _, p in plans
                             if not isinstance(p, str))
            m1, m2, m3 = st.columns(3)
            m1.metric("Tracks", len(tracks))
            m2.metric("Transitions", len(plans))
            m3.metric("Blended bars", total_bars)

            st.markdown("### 🎚️ The blends")
            for a, b, plan in plans:
                title = f"{ui.display_name(a.path)}  →  {ui.display_name(b.path)}"
                if isinstance(plan, str):
                    st.error(f"**{title}** — {plan}")
                    continue
                label, _ = ui.compat_label(plan.score)
                dot = {"Tight": "🟢", "Good": "🟢", "Workable": "🟡"}.get(label, "🔴")
                with st.expander(f"{dot}  {title}   ·   {label}", expanded=len(plans) <= 2):
                    st.markdown(ui.transition_summary(a, b, plan), unsafe_allow_html=True)
                    st.plotly_chart(ui.transition_fig(plan), width="stretch",
                                    config=theme.PLOTLY_CONFIG,
                                    key=f"tf-{a.path}-{b.path}")
                    st.caption("Dotted = outgoing track, solid = incoming. Bass and vocals "
                               "hard-swap on the mid-point downbeat so two basslines never "
                               "overlap; drums and everything else ride an equal-power crossfade.")
                    st.markdown("**Cost breakdown** " + ui.score_detail(plan.score_breakdown),
                                unsafe_allow_html=True)

            st.divider()
            r1, r2 = st.columns([3, 1])
            out_name = r1.text_input("Output filename", value="mix.wav",
                                     label_visibility="collapsed")
            render = r2.button("🔥 Mix it", type="primary", width="stretch")

            if render:
                out_path = OUTPUT_DIR / (out_name or "mix.wav")
                bar = st.progress(0.0, text="Starting…")
                try:
                    render_queue(queue_paths, out_path,
                                 progress=lambda msg, f: bar.progress(f, text=msg))
                    # Play and download the MP3: a long WAV is hundreds of MB to push
                    # through a browser. The WAV stays on disk as the lossless master.
                    if out_path.suffix.lower() == ".wav":
                        bar.progress(0.99, text="Encoding MP3 for playback…")
                        playable = audio_mod.encode_mp3(out_path)
                    else:
                        playable = out_path
                    bar.progress(1.0, text="Done")
                    st.session_state.last_mix = str(playable)
                    st.success(f"Rendered → `{out_path}`")
                except Exception as e:
                    bar.empty()
                    st.error(f"Render failed: {e}")

            last_mix = Path(st.session_state.get("last_mix", ""))
            if last_mix.is_file():
                live_player(last_mix, load_tracklist(last_mix), key="last")
                st.download_button(f"⬇️ Download {last_mix.suffix[1:].upper()}",
                                   data=lambda p=last_mix: p.read_bytes(),
                                   file_name=last_mix.name,
                                   mime="audio/mpeg" if last_mix.suffix == ".mp3"
                                   else "audio/wav")
