"""Visual language: neon club palette, animated backdrop, and shared Plotly defaults."""

from __future__ import annotations

import html

import plotly.graph_objects as go
import streamlit as st

# Plotly needs plain colours, so these stay hex; CSS uses the variables below.
BG = "#07050f"
PANEL = "#150f27"
PANEL_2 = "#1d1535"
BORDER = "#2a2142"
TEXT = "#f3efff"
MUTED = "#a49cc0"
PINK = "#ff3dcb"
VIOLET = "#8f6bff"
CYAN = "#2ee6ff"
LIME = "#b8ff4d"
YELLOW = "#ffe14d"
ORANGE = "#ff9b3d"
RED = "#ff5577"
AMBER = YELLOW
MAGENTA = PINK

#: Section colours double as the waveform tint and the legend.
SECTION_COLORS = {
    "start": "#4a4166", "intro": CYAN, "verse": "#6b8cff", "chorus": YELLOW,
    "break": LIME, "bridge": "#b18cff", "inst": "#7a6fa3", "solo": PINK,
    "outro": RED, "end": "#4a4166",
}

#: Per-stem colours, shared by the transition diagram and the DJ booth.
STEM_COLORS = {"drums": YELLOW, "bass": RED, "vocals": CYAN, "other": "#b18cff"}

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@600;800&display=swap');

:root {{
  --bg:{BG}; --panel:rgba(26,18,48,.55); --border:rgba(255,255,255,.09); --text:{TEXT};
  --muted:{MUTED}; --pink:{PINK}; --violet:{VIOLET}; --cyan:{CYAN}; --lime:{LIME};
  --yellow:{YELLOW}; --red:{RED};
  --grad:linear-gradient(120deg, {PINK} 0%, {VIOLET} 50%, {CYAN} 100%);
  --lcd:'Orbitron', 'Space Grotesk', monospace;
}}

/* ---------- club lights: drifting colour washes + faint scanlines ---------- */
html, body {{ background:var(--bg); }}
body::before {{
  content:""; position:fixed; inset:-25%; z-index:-1; pointer-events:none;
  background:
    radial-gradient(26% 24% at 18% 12%, rgba(255,61,203,.34), transparent 70%),
    radial-gradient(24% 22% at 86% 8%,  rgba(46,230,255,.24), transparent 70%),
    radial-gradient(32% 28% at 64% 92%, rgba(143,107,255,.30), transparent 70%),
    radial-gradient(20% 18% at 6% 78%,  rgba(184,255,77,.12), transparent 70%);
  filter:blur(28px); animation:aidj-drift 28s ease-in-out infinite alternate;
}}
body::after {{
  content:""; position:fixed; inset:0; z-index:-1; pointer-events:none; opacity:.5;
  background:repeating-linear-gradient(0deg, rgba(255,255,255,.022) 0 1px, transparent 1px 3px);
}}
@keyframes aidj-drift {{
  50%  {{ transform:translate3d(3%,2%,0) rotate(5deg) scale(1.05); }}
  100% {{ transform:translate3d(-3%,-2%,0) rotate(-4deg) scale(1.1); }} }}
.stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"],
header[data-testid="stHeader"] {{ background:transparent !important; }}

.block-container {{ padding-top:3.2rem; max-width:1500px; }}
#MainMenu, footer {{ visibility:hidden; }}

/* ---------- hero ---------- */
.dj-hero {{ margin:0 0 1.2rem; }}
.dj-logo {{ display:flex; align-items:center; gap:1rem; }}
.dj-disc {{
  width:58px; height:58px; border-radius:50%; flex:none; position:relative;
  background:repeating-radial-gradient(circle, #1b1530 0 1.5px, #0b0815 1.5px 3.5px);
  box-shadow:0 0 0 2px rgba(255,255,255,.07), 0 0 34px rgba(255,61,203,.55);
  animation:aidj-spin 1.9s linear infinite;
}}
.dj-disc::before {{ content:""; position:absolute; inset:31%; border-radius:50%;
  background:conic-gradient({PINK}, {VIOLET}, {CYAN}, {LIME}, {PINK}); }}
.dj-disc::after {{ content:""; position:absolute; inset:46%; border-radius:50%; background:var(--bg); }}
@keyframes aidj-spin {{ to {{ transform:rotate(360deg); }} }}
.dj-word {{
  font-family:'Unbounded', sans-serif; font-weight:800; font-size:2.35rem; line-height:1;
  letter-spacing:-.03em; background:var(--grad); -webkit-background-clip:text;
  background-clip:text; color:transparent; filter:drop-shadow(0 0 18px rgba(255,61,203,.45));
}}
.dj-eq {{ display:flex; align-items:flex-end; gap:4px; height:34px; margin-left:.2rem; }}
.dj-eq i {{ width:6px; border-radius:3px; background:var(--grad); background-size:100% 300%;
  animation:aidj-eq 1s ease-in-out infinite; }}
.dj-eq i:nth-child(1) {{ animation-delay:-.2s }} .dj-eq i:nth-child(2) {{ animation-delay:-.6s }}
.dj-eq i:nth-child(3) {{ animation-delay:-.1s }} .dj-eq i:nth-child(4) {{ animation-delay:-.8s }}
.dj-eq i:nth-child(5) {{ animation-delay:-.4s }} .dj-eq i:nth-child(6) {{ animation-delay:-.9s }}
.dj-eq i:nth-child(7) {{ animation-delay:-.3s }}
@keyframes aidj-eq {{ 0%,100% {{ height:22%; }} 30% {{ height:100%; }} 60% {{ height:48%; }} }}
.dj-tag {{ color:var(--muted); font-size:1rem; margin:.7rem 0 .9rem; max-width:52rem; }}
.dj-tag b {{ color:var(--text); }}
.dj-ticker {{ overflow:hidden; border:1px solid var(--border); border-radius:999px;
  background:rgba(0,0,0,.35); padding:.38rem 0; mask-image:linear-gradient(90deg, transparent, #000 6%, #000 94%, transparent); }}
.dj-ticker-track {{ display:inline-flex; gap:2.6rem; white-space:nowrap; padding-left:2.6rem;
  animation:aidj-ticker 32s linear infinite; font-family:var(--lcd); font-size:.72rem;
  letter-spacing:.14em; color:var(--lime); text-shadow:0 0 8px rgba(184,255,77,.6); }}
@keyframes aidj-ticker {{ to {{ transform:translateX(-50%); }} }}

/* ---------- tabs: glowing pills ---------- */
.stTabs [data-baseweb="tab-list"] {{
  gap:.35rem; border:1px solid var(--border); border-radius:999px; padding:.32rem;
  background:rgba(0,0,0,.32); width:fit-content; max-width:100%; overflow-x:auto;
}}
.stTabs [data-baseweb="tab"] {{ border-radius:999px; padding:.5rem 1.15rem; height:auto;
  font-weight:700; transition:background .2s, box-shadow .2s, transform .15s; }}
.stTabs [data-baseweb="tab"]:hover {{ background:rgba(255,255,255,.06); }}
.stTabs [aria-selected="true"] {{ background:var(--grad); color:#fff !important;
  box-shadow:0 6px 24px rgba(255,61,203,.38); }}
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] {{ display:none; }}

/* ---------- buttons ---------- */
.stButton > button, .stDownloadButton > button {{
  font-weight:700; border:1px solid var(--border); white-space:nowrap;
  padding:.42rem 1rem; min-height:0; transition:transform .12s ease, box-shadow .2s, filter .2s;
}}
.stButton > button:hover, .stDownloadButton > button:hover {{ transform:translateY(-2px);
  border-color:rgba(255,61,203,.6); box-shadow:0 6px 20px rgba(255,61,203,.18); }}
.stButton > button:active, .stDownloadButton > button:active {{ transform:scale(.96); }}
.stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"] {{
  background:var(--grad); background-size:180% 100%; border:0; color:#fff;
  box-shadow:0 8px 26px rgba(255,61,203,.38); text-shadow:0 1px 2px rgba(0,0,0,.25);
}}
.stButton > button[kind="primary"]:hover {{ background-position:100% 0; filter:brightness(1.1);
  box-shadow:0 10px 34px rgba(46,230,255,.35); }}

/* ---------- glass cards, expanders, inputs ---------- */
div[data-testid="stVerticalBlockBorderWrapper"],
div[data-testid="stExpander"] details {{
  background:var(--panel); backdrop-filter:blur(12px); -webkit-backdrop-filter:blur(12px);
  border-color:var(--border) !important; border-radius:18px !important;
  transition:border-color .25s, box-shadow .25s;
}}
div[data-testid="stVerticalBlockBorderWrapper"]:hover {{ border-color:rgba(143,107,255,.38) !important;
  box-shadow:0 0 0 1px rgba(143,107,255,.12), 0 10px 40px rgba(0,0,0,.35); }}
div[data-testid="stExpander"] summary {{ font-weight:700; }}
div[data-baseweb="input"] > div, div[data-baseweb="select"] > div, div[data-baseweb="textarea"] {{
  background:rgba(0,0,0,.35) !important; }}
[data-testid="stFileUploaderDropzone"] {{ background:rgba(0,0,0,.3);
  border:1.5px dashed rgba(255,61,203,.45); border-radius:16px; }}
[data-testid="stProgress"] div[role="progressbar"] > div > div {{ background:var(--grad) !important; }}
[data-testid="stAlertContainer"] {{ border-radius:14px; backdrop-filter:blur(8px); }}

/* ---------- sidebar ---------- */
section[data-testid="stSidebar"] {{ background:rgba(10,7,22,.72); backdrop-filter:blur(16px);
  -webkit-backdrop-filter:blur(16px); border-right:1px solid var(--border); }}
section[data-testid="stSidebar"] > div {{ background:transparent; }}
[data-testid="stMetricValue"] {{ font-family:var(--lcd); font-weight:800; font-size:1.45rem;
  background:var(--grad); -webkit-background-clip:text; background-clip:text; color:transparent; }}
[data-testid="stMetricLabel"] {{ color:var(--muted); text-transform:uppercase; letter-spacing:.08em;
  font-size:.7rem; }}

/* ---------- chips ---------- */
.chip {{ display:inline-flex; align-items:center; gap:.32rem; padding:.18rem .6rem;
  margin:.12rem .22rem .12rem 0; border-radius:999px; font-size:.74rem; font-weight:600;
  border:1px solid var(--border); background:rgba(255,255,255,.04); color:var(--muted);
  white-space:nowrap; }}
.chip b {{ color:var(--text); font-weight:700; }}
.chip-key  {{ border-color:rgba(177,140,255,.45); background:rgba(143,107,255,.14); color:#d7c8ff; }}
.chip-bpm  {{ border-color:rgba(46,230,255,.45); background:rgba(46,230,255,.1); color:{CYAN};
  font-family:var(--lcd); font-size:.68rem; letter-spacing:.04em; }}
.chip-good {{ border-color:rgba(184,255,77,.45); background:rgba(184,255,77,.1); color:{LIME}; }}
.chip-ok   {{ border-color:rgba(255,225,77,.45); background:rgba(255,225,77,.1); color:{YELLOW}; }}
.chip-bad  {{ border-color:rgba(255,85,119,.45); background:rgba(255,85,119,.1); color:{RED}; }}
.chip-muted {{ opacity:.8; }}
a.chip-link {{ text-decoration:none; }}
a.chip-link:hover {{ border-color:{CYAN}; color:{TEXT}; opacity:1; }}

/* ---------- cards & rails ---------- */
.card-title {{ font-size:1.02rem; font-weight:700; color:var(--text);
  overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
.card-sub {{ font-size:.8rem; color:var(--muted); margin-top:-.1rem; }}
.card-num {{ font-family:var(--lcd); font-size:1.35rem; font-weight:800; line-height:1;
  background:var(--grad); -webkit-background-clip:text; background-clip:text; color:transparent; }}
.vinyl {{ display:inline-block; width:2.1rem; height:2.1rem; border-radius:50%; flex:none;
  vertical-align:middle; margin-right:.6rem; position:relative;
  background:repeating-radial-gradient(circle, #1b1530 0 1px, #0b0815 1px 3px);
  box-shadow:0 0 0 1px rgba(255,255,255,.08), 0 0 16px hsla(var(--h),95%,62%,.45); }}
.vinyl::before {{ content:""; position:absolute; inset:30%; border-radius:50%;
  background:hsl(var(--h),95%,62%); }}
.vinyl::after {{ content:""; position:absolute; inset:45%; border-radius:50%; background:var(--bg); }}
div[data-testid="stVerticalBlockBorderWrapper"]:hover .vinyl {{ animation:aidj-spin 1.9s linear infinite; }}
.title-row {{ display:flex; align-items:center; min-width:0; }}
.link-rail {{ display:flex; align-items:center; gap:.55rem; margin:.1rem 0 .1rem 1.15rem;
  padding:.2rem 0 .2rem 1.1rem; border-left:2px dashed rgba(255,61,203,.35);
  font-size:.76rem; color:var(--muted); }}
.cue-time {{ font-family:var(--lcd); font-size:.78rem; color:var(--muted); white-space:nowrap; }}

/* ---------- import preview + cut sheet ---------- */
table.imp, table.cuts {{ width:100%; border-collapse:collapse; font-size:.84rem; margin:.4rem 0; }}
table.imp td, table.cuts td, table.cuts th {{ padding:.5rem .55rem; border-bottom:1px solid var(--border);
  vertical-align:middle; text-align:left; }}
table.imp tr.off {{ opacity:.45; }}
table.imp td span {{ color:var(--muted); font-size:.78rem; }}
table.imp td.st {{ width:1.6rem; font-weight:800; color:{LIME}; }}
table.imp tr.off td.st {{ color:{RED}; }}
table.imp td.tm {{ color:var(--muted); font-family:var(--lcd); font-size:.72rem; width:3.6rem; }}
table.imp td.bd {{ text-align:right; }}
table.cuts th {{ color:var(--muted); font-size:.66rem; font-weight:700; letter-spacing:.1em;
  text-transform:uppercase; }}
table.cuts td {{ white-space:nowrap; }}
table.cuts td:nth-child(n+3) {{ font-family:var(--lcd); font-size:.74rem; }}
table.cuts td:nth-child(2) {{ white-space:normal; }}
table.cuts td.n {{ color:var(--muted); font-weight:700; }}
table.cuts td.sw {{ color:{YELLOW}; font-weight:800; text-shadow:0 0 10px rgba(255,225,77,.5); }}

/* ---------- artwork ---------- */
[data-testid="stImage"] img, [data-testid="stImageContainer"] img {{ border-radius:14px; }}
div[data-testid="stVerticalBlockBorderWrapper"]:has([data-testid="stImage"]) {{ transition:transform .2s, border-color .25s, box-shadow .25s; }}
div[data-testid="stVerticalBlockBorderWrapper"]:has([data-testid="stImage"]):hover {{ transform:translateY(-3px); }}

/* ---------- scrollbars ---------- */
::-webkit-scrollbar {{ width:9px; height:9px; }}
::-webkit-scrollbar-thumb {{ background:linear-gradient({PINK}, {VIOLET}); border-radius:9px; }}
::-webkit-scrollbar-track {{ background:transparent; }}

@media (prefers-reduced-motion: reduce) {{
  *, *::before, *::after {{ animation:none !important; transition:none !important; }}
}}
</style>
"""


def inject() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def hero(tagline_html: str, ticker: list[str]) -> None:
    """Spinning-record logo, live EQ bars, tagline and a scrolling LED ticker."""
    items = "".join(f"<span>{html.escape(t)}</span>" for t in ticker)
    st.markdown(
        '<div class="dj-hero"><div class="dj-logo"><div class="dj-disc"></div>'
        '<div class="dj-word">AI DJ</div><div class="dj-eq">' + "<i></i>" * 7 + "</div></div>"
        f'<div class="dj-tag">{tagline_html}</div>'
        # the items twice over, so the -50% scroll loops seamlessly
        f'<div class="dj-ticker"><div class="dj-ticker-track">{items}{items}</div></div></div>',
        unsafe_allow_html=True,
    )


def style_fig(fig: go.Figure, height: int, *, show_x: bool = True) -> go.Figure:
    """Apply the shared dark chart styling."""
    fig.update_layout(
        height=height,
        margin=dict(l=0, r=0, t=6, b=6 if show_x else 0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=MUTED, size=11, family="Space Grotesk, sans-serif"),
        showlegend=False,
        hoverlabel=dict(bgcolor=PANEL_2, bordercolor=BORDER, font=dict(color=TEXT, size=11)),
        bargap=0,
    )
    fig.update_xaxes(showgrid=False, zeroline=False, visible=show_x,
                     linecolor=BORDER, tickcolor=BORDER)
    fig.update_yaxes(showgrid=False, zeroline=False, visible=False)
    return fig


#: Pass to st.plotly_chart so charts read as graphics, not dashboards.
PLOTLY_CONFIG = {"displayModeBar": False, "staticPlot": False, "scrollZoom": False}
