"""The DJ booth: a live, two-deck view of the mix as it plays.

Built on st.components.v2, which mounts into the app's own DOM rather than an iframe,
so its JavaScript can follow the page's real <audio> element on every frame — no
Streamlit reruns, and seeking is instant. Tracks alternate between Deck A and Deck B
like a real DJ's. Each deck's stem faders follow the mix engine's actual curves
(equal-power crossfade for drums and music; bass and vocals hard-swap mid-blend),
and the change of track lands on the bass swap — the moment the new track takes the
low end, which is when a listener hears it.
"""

from __future__ import annotations

import re
from pathlib import Path

import streamlit as st

from ..sources.base import tidy_title
from ..transition import BASS_SWAP_PROGRESS, VOCAL_HANDOFF_PROGRESS

HTML = """
<div class="booth">
  <div class="decks"></div>
  <canvas class="viz"></canvas>
  <div class="tl"><div class="tl-blocks"></div></div>
  <div class="tl-axis"><span>0:00</span><span class="legend"><i class="lg-blend"></i>blend
    <i class="lg-swap"></i>bass swap = change of track</span><span class="t-end"></span></div>
  <ol class="list"></ol>
</div>
"""

CSS = """
.booth { --c:#2ee6ff; --ca:#2ee6ff; --cb:#ff3dcb; --kick:0; --text:#f3efff; --muted:#a49cc0;
  --border:rgba(255,255,255,.09); container-type:inline-size; color:var(--text); font-family:inherit; }
.decks { display:grid; grid-template-columns:1fr minmax(170px,.62fr) 1fr; gap:12px; }

/* ---------- decks ---------- */
.deck { position:relative; overflow:hidden; border-radius:18px; padding:12px 12px 14px;
  border:1px solid var(--border); opacity:.62; transition:opacity .35s, border-color .35s, box-shadow .35s;
  background:radial-gradient(120% 90% at 0% 0%, color-mix(in srgb, var(--c) 18%, transparent), transparent 62%),
             rgba(20,14,38,.72); }
.deck.active { opacity:1; border-color:color-mix(in srgb, var(--c) 55%, transparent);
  box-shadow:0 0 0 1px color-mix(in srgb, var(--c) 22%, transparent),
             0 12px 40px color-mix(in srgb, var(--c) 20%, transparent); }
.deck.load .dtitle, .deck.load .dartist { animation:slidein .5s ease-out; }
.deck.drop::after { content:""; position:absolute; inset:0; pointer-events:none; border-radius:inherit;
  background:radial-gradient(circle at 25% 50%, color-mix(in srgb, var(--c) 55%, transparent), transparent 65%);
  animation:drop 1.1s ease-out forwards; }
@keyframes drop { from { opacity:1; transform:scale(.97); } to { opacity:0; transform:scale(1.05); } }
@keyframes slidein { from { transform:translateY(8px); opacity:0; } to { transform:none; opacity:1; } }
@keyframes blink { 50% { opacity:.4; } }
@keyframes spin { to { transform:rotate(360deg); } }
.deck-top { display:flex; justify-content:space-between; align-items:center; margin-bottom:9px; }
.deck-name { font-family:'Unbounded',sans-serif; font-weight:800; font-size:.68rem; letter-spacing:.14em;
  color:var(--muted); }
.deck.active .deck-name { color:var(--c); text-shadow:0 0 10px color-mix(in srgb, var(--c) 60%, transparent); }
.led { font-family:'Orbitron',monospace; font-size:.58rem; font-weight:800; letter-spacing:.12em;
  padding:3px 8px; border-radius:999px; border:1px solid var(--border); color:var(--muted); }
.led.live { color:#b8ff4d; border-color:rgba(184,255,77,.55); background:rgba(184,255,77,.12);
  box-shadow:0 0 14px rgba(184,255,77,.35); }
.led.in { color:#ffe14d; border-color:rgba(255,225,77,.55); background:rgba(255,225,77,.12);
  animation:blink 1s infinite; }
.led.out { color:#ff3dcb; border-color:rgba(255,61,203,.55); background:rgba(255,61,203,.12); }
.led.cue { color:#2ee6ff; border-color:rgba(46,230,255,.4); }
.dbody { display:flex; gap:12px; align-items:center; min-width:0; }

/* turntable */
.platter { position:relative; flex:none; width:clamp(66px, 10cqw, 112px); aspect-ratio:1; border-radius:50%;
  background:radial-gradient(circle, #1c1532 62%, #0c0917 63%);
  box-shadow:inset 0 0 0 2px rgba(255,255,255,.05), 0 8px 22px rgba(0,0,0,.55); }
.platter::after { content:""; position:absolute; inset:6%; border-radius:50%; pointer-events:none;
  background:conic-gradient(from 210deg, transparent 0 18deg, rgba(255,255,255,.13) 34deg, transparent 52deg 190deg,
             rgba(255,255,255,.07) 214deg, transparent 236deg); }
.vinyl { position:absolute; inset:6%; border-radius:50%;
  background:repeating-radial-gradient(circle, #1b1530 0 1.2px, #08060f 1.2px 3px);
  animation:spin 1.875s linear infinite; animation-play-state:paused;
  box-shadow:0 0 calc(8px + var(--kick) * 30px) color-mix(in srgb, var(--c) calc(25% + var(--kick) * 55%), transparent); }
.vlabel { position:absolute; inset:31%; border-radius:50%;
  background:conic-gradient(var(--c), #8f6bff, var(--c)); }
.vlabel::before { content:""; position:absolute; left:46%; top:9%; width:8%; height:24%; border-radius:2px;
  background:rgba(255,255,255,.9); }
.vlabel::after { content:""; position:absolute; inset:42%; border-radius:50%; background:#07050f; }
.arm { position:absolute; right:-10%; top:2%; width:52%; height:5px; border-radius:3px;
  background:linear-gradient(90deg, #8a83a3, #e4def5); transform-origin:100% 50%; transform:rotate(-36deg);
  transition:transform .7s cubic-bezier(.3,1.4,.5,1); box-shadow:0 2px 5px rgba(0,0,0,.6); }
.arm::before { content:""; position:absolute; left:-4px; top:-3px; width:9px; height:11px; border-radius:2px; background:#cfc7e8; }
.deck.active .arm { transform:rotate(-14deg); }

.dinfo { min-width:0; flex:1; }
.dtitle { font-weight:700; font-size:1.02rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.dartist { color:var(--muted); font-size:.78rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.lcdrow { display:flex; align-items:baseline; gap:6px; margin:6px 0 8px; flex-wrap:wrap; }
.lcd { font-family:'Orbitron',monospace; font-weight:800; color:var(--c);
  text-shadow:0 0 10px color-mix(in srgb, var(--c) 70%, transparent); }
.lcd.big { font-size:1.22rem; line-height:1; }
.lcd-u { font-family:'Orbitron',monospace; font-size:.52rem; letter-spacing:.12em; color:var(--muted); }
.lcd.small { font-size:.7rem; margin-left:auto; color:var(--text); text-shadow:none; opacity:.85; }
.kchip { font-size:.64rem; font-weight:700; padding:1px 7px; border-radius:999px;
  border:1px solid rgba(177,140,255,.45); background:rgba(143,107,255,.14); color:#d7c8ff; }

/* stem faders */
.stems { display:grid; grid-template-columns:repeat(4, 1fr); gap:6px; }
.stem { display:flex; flex-direction:column; align-items:center; gap:3px; }
.stem b { font-family:'Orbitron',monospace; font-size:.48rem; letter-spacing:.08em; color:var(--muted); }
.meter { position:relative; width:100%; height:34px; overflow:hidden; border-radius:6px;
  background:repeating-linear-gradient(0deg, rgba(0,0,0,.55) 0 3px, rgba(0,0,0,.35) 3px 4px);
  border:1px solid var(--border); }
.meter i { position:absolute; left:0; right:0; bottom:0; height:100%; transform-origin:bottom;
  transform:scaleY(0); transition:transform .07s linear;
  background:linear-gradient(to top, var(--sc), color-mix(in srgb, var(--sc) 45%, white));
  box-shadow:0 0 12px var(--sc); }
.stem[data-stem="drums"] { --sc:#ffe14d; } .stem[data-stem="bass"] { --sc:#ff5577; }
.stem[data-stem="vocals"] { --sc:#2ee6ff; } .stem[data-stem="other"] { --sc:#b18cff; }

/* ---------- mixer ---------- */
.mixer { display:flex; flex-direction:column; align-items:center; justify-content:center; gap:6px;
  text-align:center; padding:12px; border-radius:18px; border:1px solid var(--border);
  background:linear-gradient(180deg, rgba(32,23,60,.88), rgba(13,9,27,.88)); min-width:0; }
.m-title { font-family:'Unbounded',sans-serif; font-weight:800; font-size:.62rem; letter-spacing:.22em; color:var(--muted); }
.m-bpm { font-family:'Orbitron',monospace; font-weight:800; font-size:2.1rem; line-height:1;
  background:linear-gradient(120deg, #ff3dcb, #8f6bff, #2ee6ff); -webkit-background-clip:text;
  background-clip:text; color:transparent; filter:drop-shadow(0 0 10px rgba(255,61,203,.45));
  transform:scale(calc(1 + var(--kick) * .08)); }
.m-unit { font-family:'Orbitron',monospace; font-size:.5rem; letter-spacing:.18em; color:var(--muted); margin-top:-2px; }
.swap { display:flex; align-items:center; gap:6px; margin-top:4px; padding:4px 10px; border-radius:999px;
  font-family:'Orbitron',monospace; font-size:.56rem; letter-spacing:.12em; color:var(--muted);
  border:1px solid var(--border); transition:background .2s, color .2s, box-shadow .2s; white-space:nowrap; }
.bulb { width:9px; height:9px; border-radius:50%; background:#3a3150; flex:none; }
.swap.armed { color:#ffe14d; border-color:rgba(255,225,77,.45); }
.swap.armed .bulb { background:#ffe14d; box-shadow:0 0 10px #ffe14d; animation:blink .5s infinite; }
.swap.hit { color:#07050f; background:#ffe14d; box-shadow:0 0 30px #ffe14d; }
.swap.hit .bulb { background:#fff; }
.swap.done { color:#b8ff4d; border-color:rgba(184,255,77,.4); }
.swap.done .bulb { background:#b8ff4d; box-shadow:0 0 8px #b8ff4d; }
.xf { display:flex; align-items:center; gap:8px; width:100%; margin-top:8px;
  font-family:'Orbitron',monospace; font-size:.58rem; color:var(--muted); }
.xf-track { position:relative; flex:1; height:8px; border-radius:999px; opacity:.9;
  background:linear-gradient(90deg, var(--ca), var(--cb)); box-shadow:inset 0 0 0 1px rgba(0,0,0,.45); }
.xf-knob { position:absolute; top:50%; left:0; width:20px; height:28px; margin:-14px 0 0 -10px; border-radius:6px;
  background:linear-gradient(#f3efff, #9b93b8); transition:left .12s linear;
  box-shadow:0 3px 10px rgba(0,0,0,.6), 0 0 16px rgba(255,255,255,.35); }
.xf-knob::after { content:""; position:absolute; left:50%; top:5px; bottom:5px; width:2px; margin-left:-1px;
  border-radius:1px; background:#07050f; }
.m-state { font-size:.74rem; margin-top:4px; max-width:100%; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }

/* ---------- visualizer, timeline, tracklist ---------- */
.viz { display:block; width:100%; height:84px; margin:12px 0 10px; border-radius:14px; border:1px solid var(--border);
  background:radial-gradient(60% 130% at 50% 100%, rgba(143,107,255,.2), transparent 70%), rgba(0,0,0,.38); }
.tl { position:relative; height:60px; border-radius:12px; overflow:hidden; border:1px solid var(--border);
  background:rgba(0,0,0,.35); }
.tl-blocks { position:absolute; inset:5px 6px; }
.blk { position:absolute; height:calc(50% - 2px); border:0; border-radius:6px; padding:0 6px; display:flex;
  align-items:center; gap:5px; cursor:pointer; overflow:hidden; text-align:left; font:inherit; font-size:.68rem;
  color:var(--text); opacity:.62; background:color-mix(in srgb, var(--c) 30%, #0a0716); transition:opacity .2s; }
.blk:hover { opacity:1; }
.blk.on { opacity:1; background:color-mix(in srgb, var(--c) 62%, #0a0716); box-shadow:0 0 0 1px var(--c) inset, 0 0 14px color-mix(in srgb, var(--c) 50%, transparent); }
.blk.in { opacity:1; box-shadow:0 0 0 1px var(--c) inset; animation:blink 1.1s infinite; }
.blk-n { font-family:'Orbitron',monospace; font-weight:800; font-size:.6rem; }
.blk-t { white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.blend { position:absolute; top:0; bottom:0; pointer-events:none;
  border-left:1px dashed rgba(255,255,255,.25); border-right:1px dashed rgba(255,255,255,.25);
  background:repeating-linear-gradient(135deg, rgba(255,255,255,.09) 0 5px, transparent 5px 10px); }
.swapline { position:absolute; top:-5px; bottom:-5px; width:2px; margin-left:-1px; background:#ffe14d;
  opacity:.75; pointer-events:none; box-shadow:0 0 6px #ffe14d; }
.head { position:absolute; top:-5px; bottom:-5px; width:2px; margin-left:-1px; background:#fff;
  box-shadow:0 0 10px #fff, 0 0 20px #ff3dcb; pointer-events:none; left:0; }
.tl-axis { display:flex; justify-content:space-between; align-items:center; gap:8px; margin:6px 4px 0;
  color:var(--muted); font-family:'Orbitron',monospace; font-size:.6rem; letter-spacing:.06em; }
.legend { display:flex; align-items:center; gap:6px; font-family:inherit; }
.legend i { display:inline-block; width:14px; height:9px; border-radius:2px; }
.lg-blend { margin-left:4px; border:1px dashed rgba(255,255,255,.3);
  background:repeating-linear-gradient(135deg, rgba(255,255,255,.35) 0 3px, transparent 3px 6px); }
.lg-swap { width:3px !important; margin-left:10px; background:#ffe14d; box-shadow:0 0 6px #ffe14d; }
.list { list-style:none; margin:12px 0 0; padding:0; display:flex; flex-direction:column; gap:3px; }
.row { display:flex; align-items:center; gap:10px; padding-right:6px; border-radius:11px;
  border:1px solid transparent; transition:background .25s; }
.row.on { background:linear-gradient(90deg, color-mix(in srgb, var(--c) 22%, transparent), transparent);
  border-color:color-mix(in srgb, var(--c) 35%, transparent); }
.row.in { border-color:rgba(255,225,77,.45); }
.row-main { flex:1; min-width:0; display:flex; align-items:center; gap:12px; padding:7px 8px; cursor:pointer;
  background:none; border:0; color:var(--text); font:inherit; text-align:left; }
.row-main:hover .row-title { color:var(--c); }
.row-n { font-family:'Orbitron',monospace; font-size:.66rem; font-weight:800; color:var(--c); width:1.9em; flex:none; }
.row-time { font-family:'Orbitron',monospace; font-size:.66rem; color:var(--muted); width:4.2em; flex:none; }
.row-title { font-weight:650; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; transition:color .2s; }
.row-meta { display:flex; gap:5px; flex-wrap:wrap; justify-content:flex-end; }
.chip { font-size:.68rem; font-weight:650; padding:2px 8px; border-radius:999px; white-space:nowrap;
  border:1px solid var(--border); background:rgba(255,255,255,.04); color:var(--muted); text-decoration:none; }
.chip.bpm { font-family:'Orbitron',monospace; font-size:.6rem; color:#2ee6ff; border-color:rgba(46,230,255,.45); background:rgba(46,230,255,.1); }
.chip.key { color:#d7c8ff; border-color:rgba(177,140,255,.45); background:rgba(143,107,255,.14); }
a.chip:hover { border-color:#2ee6ff; color:var(--text); }

/* ---------- smaller screens ---------- */
@container (max-width: 760px) {
  .decks { grid-template-columns:1fr 1fr; }
  .mixer { grid-column:1 / -1; order:3; flex-direction:row; flex-wrap:wrap; column-gap:12px; row-gap:4px; }
  .m-title { display:none; } .m-bpm { font-size:1.5rem; } .m-unit { margin:0; }
  .xf, .m-state { flex-basis:100%; }
}
@container (max-width: 470px) {
  .decks { grid-template-columns:1fr; }
  .row-meta { display:none; }
}
@media (prefers-reduced-motion: reduce) {
  .vinyl, .led.in, .blk.in, .swap.armed .bulb { animation:none !important; }
  .deck.drop::after { display:none; }
}
"""

JS = r"""
export default function (component) {
  const { data, parentElement } = component;
  const root = parentElement.querySelector(".booth");
  if (!root || !data || !Array.isArray(data.tracks) || !data.tracks.length) return;

  // ------------------------------------------------------------------ data
  const tracks = data.tracks.map((t) => ({ ...t }));
  const duration = data.duration || tracks[tracks.length - 1].end || 1;
  const SWAP = data.swap_progress ?? 0.5, VOX = data.vocal_progress ?? 0.5;
  tracks.forEach((t, i) => {  // tracklists rendered before cut timings carry only `start`
    const next = tracks[i + 1];
    if (t.end == null) t.end = next ? next.start : duration;
    if (i > 0 && t.swap == null) t.swap = (t.start + tracks[i - 1].end) / 2;
  });
  const STEMS = ["drums", "bass", "vocals", "other"];
  const COLORS = ["#2ee6ff", "#ff3dcb", "#b8ff4d", "#ffe14d", "#8f6bff", "#ff9b3d", "#5cf2c3", "#ff5577"];
  const hue = (i) => COLORS[((i % COLORS.length) + COLORS.length) % COLORS.length];

  // --------------------------------------------------------------- helpers
  const q = (s) => root.querySelector(s);
  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;  // never innerHTML: titles come from catalogs
    return e;
  };
  const fmt = (s) => { s = Math.max(0, Math.floor(s || 0));
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };
  const pct = (s) => `${Math.min(100, Math.max(0, (s / duration) * 100))}%`;
  const safeUrl = (u) => (typeof u === "string" && /^https?:\/\//i.test(u.trim()) ? u.trim() : null);
  const link = (cls, text, url) => {
    const a = el("a", cls, `${text} ↗`); a.href = url; a.target = "_blank"; a.rel = "noopener"; return a;
  };
  const flash = (node, cls, ms) => { node.classList.remove(cls); void node.offsetWidth;
    node.classList.add(cls); setTimeout(() => node.classList.remove(cls), ms); };

  // ----------------------------------------------------------------- decks
  const decksEl = q(".decks");
  decksEl.textContent = "";  // the module re-runs when data changes
  function buildDeck(d) {
    const box = el("div", "deck");
    const top = el("div", "deck-top");
    const led = el("span", "led", "IDLE");
    top.append(el("span", "deck-name", d ? "DECK B" : "DECK A"), led);
    const platter = el("div", "platter"), vinyl = el("div", "vinyl");
    vinyl.append(el("div", "vlabel"));
    platter.append(vinyl, el("div", "arm"));
    const info = el("div", "dinfo");
    const title = el("div", "dtitle", "—"), artist = el("div", "dartist", "");
    const row = el("div", "lcdrow");
    const bpm = el("span", "lcd big", "---"), key = el("span", "kchip", ""), left = el("span", "lcd small", "");
    row.append(bpm, el("span", "lcd-u", "BPM"), key, left);
    const stems = el("div", "stems"), meters = {};
    [["drums", "DRM"], ["bass", "BASS"], ["vocals", "VOX"], ["other", "MUS"]].forEach(([s, label]) => {
      const box2 = el("div", "stem"); box2.dataset.stem = s;
      const m = el("div", "meter"), fill = el("i");
      m.append(fill); box2.append(m, el("b", null, label)); stems.append(box2); meters[s] = fill;
    });
    info.append(title, artist, row, stems);
    const body = el("div", "dbody"); body.append(platter, info);
    box.append(top, body);
    return { box, led, vinyl, title, artist, bpm, key, left, meters, track: -2, role: "" };
  }
  const decks = [buildDeck(0), buildDeck(1)];
  const mixer = (() => {
    const box = el("div", "mixer");
    const bpm = el("div", "m-bpm", "---");
    const swap = el("div", "swap"), swapIn = el("span", null, "");
    swap.append(el("span", "bulb"), el("span", null, "BASS SWAP"), swapIn);
    const xf = el("div", "xf"), track = el("div", "xf-track"), knob = el("div", "xf-knob");
    track.append(knob); xf.append(el("span", null, "A"), track, el("span", null, "B"));
    const state = el("div", "m-state", "Press play ▶");
    box.append(el("div", "m-title", "MIXER"), bpm, el("div", "m-unit", "MASTER BPM"), swap, xf, state);
    return { box, bpm, swap, swapIn, knob, state };
  })();
  decksEl.append(decks[0].box, mixer.box, decks[1].box);

  // --------------------------------------------------------------- timeline
  const blocks = q(".tl-blocks");
  blocks.textContent = "";
  const blockEls = tracks.map((t, i) => {
    const b = el("button", "blk");
    b.style.left = pct(t.start);
    b.style.width = `max(4px, calc(${pct(t.end - t.start)} - 2px))`;
    b.style.top = i % 2 ? "calc(50% + 2px)" : "0";
    b.style.setProperty("--c", hue(i));
    b.title = `${i + 1}. ${t.title} · Deck ${i % 2 ? "B" : "A"} · in at ${fmt(t.start)}`;
    b.append(el("span", "blk-n", String(i + 1)), el("span", "blk-t", t.title));
    b.addEventListener("click", () => seek(t.start));
    blocks.append(b);
    return b;
  });
  tracks.forEach((t, i) => {
    if (i === 0) return;
    const z = el("div", "blend");
    z.style.left = pct(t.start); z.style.width = pct(tracks[i - 1].end - t.start);
    const s = el("div", "swapline"); s.style.left = pct(t.swap);
    blocks.append(z, s);
  });
  const head = el("div", "head");
  blocks.append(head);
  q(".t-end").textContent = fmt(duration);

  // -------------------------------------------------------------- tracklist
  const list = q(".list");
  list.textContent = "";
  const rowEls = tracks.map((t, i) => {
    const li = el("li", "row");
    li.style.setProperty("--c", hue(i));
    const main = el("button", "row-main");
    main.title = "Drop the needle here";
    main.append(el("span", "row-n", String(i + 1).padStart(2, "0")),
                el("span", "row-time", fmt(t.start)), el("span", "row-title", t.title));
    main.addEventListener("click", () => seek(t.start));
    const meta = el("span", "row-meta");
    if (t.bpm) meta.append(el("span", "chip bpm", `${Math.round(t.bpm)} BPM`));
    if (t.key) meta.append(el("span", "chip key", t.key));
    const lic = safeUrl(t.license_url);
    if (t.license) meta.append(lic ? link("chip", t.license, lic) : el("span", "chip", t.license));
    const src = safeUrl(t.page_url);
    if (src) meta.append(link("chip", "source", src));
    li.append(main, meta);
    list.append(li);
    return li;
  });

  // ------------------------------------------------------------ mix state
  // During a blend both tracks play; the change of track lands on the bass swap.
  function stateAt(t) {
    for (let k = 1; k < tracks.length; k++) {
      const a = tracks[k - 1], b = tracks[k];
      if (t >= b.start && t < a.end) {
        const p = Math.min(1, Math.max(0, (t - b.start) / Math.max(1e-3, a.end - b.start)));
        return { now: t >= b.swap ? k : k - 1, from: k - 1, to: k, p };
      }
    }
    let now = 0;
    tracks.forEach((x, i) => { if (t >= x.start) now = i; });
    return { now, from: -1, to: -1, p: 0 };
  }
  const full = { drums: 1, bass: 1, vocals: 1, other: 1 }, none = { drums: 0, bass: 0, vocals: 0, other: 0 };
  function deckViews(s, t) {
    const view = [{ i: -1, role: "idle", g: none }, { i: -1, role: "idle", g: none }];
    let xf;
    if (s.from >= 0) {
      const p = s.p, swapped = t >= tracks[s.to].swap;
      const fadeOut = Math.cos(p * Math.PI / 2), fadeIn = Math.sin(p * Math.PI / 2);
      view[s.from % 2] = { i: s.from, role: swapped ? "out" : "live",
        g: { drums: fadeOut, other: fadeOut, bass: p < SWAP ? 1 : 0, vocals: p < VOX ? 1 : 0 } };
      view[s.to % 2] = { i: s.to, role: swapped ? "live" : "in",
        g: { drums: fadeIn, other: fadeIn, bass: p < SWAP ? 0 : 1, vocals: p < VOX ? 0 : 1 } };
      xf = s.from % 2 === 0 ? p : 1 - p;
    } else {
      view[s.now % 2] = { i: s.now, role: "live", g: full };
      if (s.now + 1 < tracks.length) view[(s.now + 1) % 2] = { i: s.now + 1, role: "cue", g: none };
      xf = s.now % 2;
    }
    return { view, xf };
  }

  // ----------------------------------------------- audio analysis (listen-only)
  // captureStream() observes the element without rerouting its output, so if anything
  // here fails the music still plays; the visualizer just falls back to an idle wave.
  const caps = window.__aidjCaps || (window.__aidjCaps = new WeakMap());
  function analyserFor(a) {
    if (!a || typeof a.captureStream !== "function") return null;
    if (caps.has(a)) return caps.get(a);
    try {
      const AC = window.AudioContext || window.webkitAudioContext;
      const ctx = window.__aidjCtx || (window.__aidjCtx = new AC());
      const stream = a.captureStream();
      if (!stream.getAudioTracks().length) return null;  // not decoded yet: retry on "playing"
      const an = ctx.createAnalyser();
      an.fftSize = 1024; an.smoothingTimeConstant = 0.78;
      const mute = ctx.createGain(); mute.gain.value = 0;  // keeps the graph pulled, adds no sound
      ctx.createMediaStreamSource(stream).connect(an);
      an.connect(mute); mute.connect(ctx.destination);
      const rec = { an, bins: new Uint8Array(an.frequencyBinCount), rate: ctx.sampleRate, ctx };
      caps.set(a, rec);
      return rec;
    } catch (e) { return null; }
  }
  function band(rec, lo, hi) {
    const hz = rec.rate / 2 / rec.bins.length;
    let s = 0, n = 0;
    for (let j = Math.max(1, Math.floor(lo / hz)); j <= Math.min(rec.bins.length - 1, Math.ceil(hi / hz)); j++) {
      s += rec.bins[j]; n++;
    }
    return n ? s / n / 255 : 0;
  }

  // ------------------------------------------------------------- visualizer
  const canvas = q("canvas.viz"), g2 = canvas.getContext("2d");
  let dpr = 1;
  const sizeCanvas = () => {
    const r = canvas.getBoundingClientRect(); dpr = Math.min(2, window.devicePixelRatio || 1);
    canvas.width = Math.max(1, Math.round(r.width * dpr)); canvas.height = Math.max(1, Math.round(r.height * dpr));
  };
  const ro = new ResizeObserver(sizeCanvas); ro.observe(canvas); sizeCanvas();
  const BARS = 56, levels = new Float32Array(BARS);
  function drawViz(colA, colB) {
    const W = canvas.width, H = canvas.height;
    g2.clearRect(0, 0, W, H);
    const grad = g2.createLinearGradient(0, 0, W, 0);
    grad.addColorStop(0, colA); grad.addColorStop(0.5, "#8f6bff"); grad.addColorStop(1, colB);
    g2.fillStyle = grad; g2.shadowColor = "rgba(255,61,203,.55)"; g2.shadowBlur = 10 * dpr;
    const gap = W / BARS, bw = Math.max(1, gap * 0.6);
    for (let i = 0; i < BARS; i++) {
      const h = Math.max(2 * dpr, levels[i] * H * 0.9), x = i * gap + (gap - bw) / 2, y = (H - h) / 2;
      g2.beginPath();
      if (g2.roundRect) g2.roundRect(x, y, bw, h, bw / 2); else g2.rect(x, y, bw, h);
      g2.fill();
    }
  }

  // --------------------------------------------------------------- painting
  const ROLE = { live: "LIVE", in: "MIXING IN", out: "MIXING OUT", cue: "CUED", idle: "IDLE" };
  let audio = null, current = -1, incoming = -1, lastSwapState = "";
  function paint(t, playing) {
    const s = stateAt(t), { view, xf } = deckViews(s, t);
    const rec = playing ? analyserFor(audio) : null;
    if (rec) {
      if (rec.ctx.state === "suspended") rec.ctx.resume().catch(() => {});
      rec.an.getByteFrequencyData(rec.bins);
    }
    const energy = rec ? {
      bass: band(rec, 30, 180), drums: Math.max(band(rec, 40, 120), band(rec, 3500, 11000) * 1.4),
      vocals: band(rec, 300, 3000), other: band(rec, 500, 6000) } : null;
    const kick = rec ? Math.max(0, Math.min(1, (energy.bass - 0.45) * 2.4)) : 0;
    root.style.setProperty("--kick", kick.toFixed(3));

    // decks
    view.forEach((v, d) => {
      const dk = decks[d];
      if (v.i !== dk.track) {  // a new record lands on this deck
        dk.track = v.i;
        const tr = tracks[v.i];
        dk.title.textContent = tr ? tr.title : "—";
        dk.artist.textContent = tr ? (tr.artist || "") : "";
        dk.bpm.textContent = tr && tr.bpm ? String(Math.round(tr.bpm)) : "---";
        dk.key.textContent = tr && tr.key ? tr.key : "";
        dk.key.style.display = tr && tr.key ? "" : "none";
        dk.box.style.setProperty("--c", tr ? hue(v.i) : "#4a4166");
        dk.vinyl.style.animationDuration = `${240 / ((tr && tr.bpm) || 120)}s`;  // one turn per bar
        if (tr) flash(dk.box, "load", 600);
      }
      if (v.role !== dk.role) {
        if (v.role === "live" && dk.role === "in") flash(dk.box, "drop", 1100);  // the change of track
        dk.role = v.role;
        dk.led.textContent = ROLE[v.role]; dk.led.className = `led ${v.role}`;
        dk.box.classList.toggle("active", v.role === "live" || v.role === "in" || v.role === "out");
      }
      dk.vinyl.style.animationPlayState = playing && dk.box.classList.contains("active") ? "running" : "paused";
      const tr = tracks[v.i];
      dk.left.textContent = tr ? `-${fmt(tr.end - Math.max(t, tr.start))}` : "";
      STEMS.forEach((stem, k) => {
        const g = v.g[stem];
        const wobble = energy ? 0.3 + 0.7 * Math.min(1, energy[stem] * 1.35)
                              : (playing ? 0.62 + 0.18 * Math.sin(t * 7 + k * 1.7 + d) : 0.42);
        dk.meters[stem].style.transform = `scaleY(${(g * wobble).toFixed(3)})`;
      });
    });
    root.style.setProperty("--ca", decks[0].track >= 0 ? hue(decks[0].track) : "#4a4166");
    root.style.setProperty("--cb", decks[1].track >= 0 ? hue(decks[1].track) : "#4a4166");

    // mixer
    mixer.knob.style.left = `${(xf * 100).toFixed(2)}%`;
    let swapState = "";
    if (s.from >= 0) {
      const b = tracks[s.to], toSwap = b.swap - t;
      mixer.bpm.textContent = String(Math.round(b.bpm || tracks[s.now].bpm || 0));  // blends run at the incoming tempo
      swapState = toSwap > 0 ? "armed" : (toSwap > -1.4 ? "hit" : "done");
      mixer.swapIn.textContent = toSwap > 0 ? ` ${fmt(Math.ceil(toSwap))}` : " ✓";
      mixer.state.textContent = toSwap > 0 ? `Blending into ${b.title}` : `${b.title} has the floor`;
    } else {
      mixer.bpm.textContent = String(Math.round(tracks[s.now].bpm || 0));
      mixer.swapIn.textContent = "";
      const nx = tracks[s.now + 1];
      mixer.state.textContent = !playing && t < 0.5 ? "Press play ▶"
        : (nx ? `Next mix in ${fmt(nx.start - t)}` : "Final track — enjoy the ride");
    }
    if (swapState !== lastSwapState) { mixer.swap.className = `swap ${swapState}`; lastSwapState = swapState; }

    // timeline + tracklist highlights
    if (s.now !== current) {
      current = s.now;
      blockEls.forEach((b, j) => b.classList.toggle("on", j === current));
      rowEls.forEach((r, j) => r.classList.toggle("on", j === current));
    }
    const other = s.from < 0 ? -1 : (s.now === s.from ? s.to : s.from);
    if (other !== incoming) {
      incoming = other;
      blockEls.forEach((b, j) => b.classList.toggle("in", j === other));
      rowEls.forEach((r, j) => r.classList.toggle("in", j === other));
    }
    head.style.left = pct(t);

    // visualizer: real spectrum when we can hear it, a calm idle wave otherwise
    const half = BARS / 2;
    if (rec) {
      const n = rec.bins.length;
      for (let k = 0; k < half; k++) {  // log-spaced bands, lows in the centre
        const lo = Math.floor(Math.pow(n * 0.7, k / half)), hi = Math.max(lo + 1, Math.floor(Math.pow(n * 0.7, (k + 1) / half)));
        let m = 0;
        for (let j = lo; j < hi && j < n; j++) m = Math.max(m, rec.bins[j]);
        const v = Math.pow(m / 255, 1.5);
        levels[half - 1 - k] = levels[half - 1 - k] * 0.35 + v * 0.65;
        levels[half + k] = levels[half - 1 - k];
      }
    } else {
      // Idle: two slow travelling waves — alive, but clearly not pretending to be audio.
      // Playing without an analyser (Safari/Firefox): the same waves pulse on the beat.
      const now = performance.now() / 1000, tr = tracks[s.now];
      const beat = playing && tr && tr.bpm ? Math.exp(-(((t - tr.start) * tr.bpm / 60) % 1) * 5) : 0;
      for (let k = 0; k < half; k++) {
        const x = k / half;
        const w = 0.5 + 0.5 * Math.sin(now * 1.6 - x * 7) * Math.cos(now * 0.7 + x * 3);
        const v = (playing ? 0.16 : 0.07) + w * (playing ? 0.26 : 0.17) * (1 - x * 0.55) + beat * 0.3 * (1 - x);
        levels[half - 1 - k] = v; levels[half + k] = v;
      }
    }
    const ca = decks[0].track >= 0 ? hue(decks[0].track) : "#2ee6ff";
    const cb = decks[1].track >= 0 ? hue(decks[1].track) : "#ff3dcb";
    drawViz(ca, cb);
  }

  // ------------------------------------------------------------- the loop
  let raf = 0, visible = true, last = 0;
  const io = new IntersectionObserver((es) => { visible = es.some((e) => e.isIntersecting); });
  io.observe(root);
  function frame(ts) {
    raf = requestAnimationFrame(frame);
    if (!visible) return;
    const playing = !!(audio && !audio.paused && !audio.ended);
    if (!playing && ts - last < 66) return;  // ~15 fps while idle
    last = ts;
    paint(audio ? audio.currentTime : 0, playing);
  }
  raf = requestAnimationFrame(frame);

  // ---------------------------------------------- bind to the <audio> element
  const onPlaying = () => analyserFor(audio);
  function bind() {
    const a = document.querySelector(`.st-key-${CSS.escape(data.anchor)} audio`);
    if (a === audio) return;
    if (audio) audio.removeEventListener("playing", onPlaying);
    audio = a;
    if (audio) audio.addEventListener("playing", onPlaying);
  }
  function seek(s) {
    bind();
    if (!audio) return;
    audio.currentTime = s;
    audio.play().catch(() => {});  // a click is a user gesture, so play is allowed
  }
  // Streamlit may replace the <audio> element on a rerun: re-bind when it does.
  const observer = new MutationObserver(bind);
  observer.observe(document.body, { childList: true, subtree: true });
  bind();

  return () => {
    cancelAnimationFrame(raf); observer.disconnect(); io.disconnect(); ro.disconnect();
    if (audio) audio.removeEventListener("playing", onPlaying);
  };
}
"""

#: Registered once at import — re-registering on every rerun would churn the component.
_BOOTH = st.components.v2.component("aidj_dj_booth", html=HTML, css=CSS, js=JS)

_MIME = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".flac": "audio/flac"}


def _http_only(url: str | None) -> str | None:
    return url.strip() if isinstance(url, str) and url.strip().lower().startswith(
        ("http://", "https://")) else None


def player_data(anchor: str, tracklist: dict) -> dict:
    tracks = []
    for cue in tracklist.get("tracks", []):
        credit = cue.get("credit") or {}
        artist = credit.get("artist")
        title = (tidy_title(artist, credit["title"]) if artist and credit.get("title")
                 else cue.get("title", ""))
        tracks.append({
            "title": title, "artist": artist, "bpm": cue.get("bpm"), "key": cue.get("camelot"),
            "start": cue.get("start", 0.0), "end": cue.get("end"), "swap": cue.get("swap"),
            "license": credit.get("license"), "license_url": _http_only(credit.get("license_url")),
            "page_url": _http_only(credit.get("page_url")),
        })
    return {"anchor": anchor, "duration": tracklist.get("duration"),
            "swap_progress": BASS_SWAP_PROGRESS, "vocal_progress": VOCAL_HANDOFF_PROGRESS,
            "tracks": tracks}


def live_player(audio_path: Path, tracklist: dict | None, key: str) -> None:
    """Audio player plus the live DJ booth: decks, mixer, visualizer, timeline, tracklist."""
    anchor = re.sub(r"[^a-z0-9_-]", "-", f"mixplayer-{key}".lower())
    with st.container(key=anchor):
        st.audio(str(audio_path), format=_MIME.get(audio_path.suffix.lower(), "audio/wav"))
    if tracklist and tracklist.get("tracks"):
        _BOOTH(data=player_data(anchor, tracklist), key=f"booth-{anchor}")
