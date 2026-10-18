"""Reusable UI pieces: chips, waveforms, section timelines, transition diagrams."""

from __future__ import annotations

import hashlib
import html
from pathlib import Path

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .. import audio as audio_mod
from ..sources import credits
from ..sources.base import display_name as file_display_name
from ..sources.base import tidy_title  # noqa: F401  (re-exported for the UI)
from ..transition import (BASS_SWAP_PROGRESS, FALLBACK_EDGE_BARS, VOCAL_HANDOFF_PROGRESS,
                          intro_window, outro_window)
from ..types import TrackAnalysis, TransitionPlan
from . import theme

#: Compatibility score bands. Score is a cost, so lower is better.
COMPAT_BANDS = [
    (2.0, "Tight", "chip-good"),
    (4.0, "Good", "chip-good"),
    (7.0, "Workable", "chip-ok"),
    (float("inf"), "Rough", "chip-bad"),
]


# --------------------------------------------------------------------- text


def fmt_duration(seconds: float) -> str:
    m, s = divmod(int(round(seconds)), 60)
    return f"{m}:{s:02d}"


def chip(text: str, value: str | None = None, kind: str = "") -> str:
    """One inline pill. Returns HTML — caller batches them into a single markdown call."""
    parts = []
    if text:
        parts.append(html.escape(text))
    if value is not None:
        parts.append(f"<b>{html.escape(str(value))}</b>")
    return f'<span class="chip {kind}">{" ".join(parts)}</span>'


def link_chip(text: str, url: str | None, kind: str = "chip-muted") -> str:
    """A chip that opens `url` in a new tab — licences and sources stay one click away."""
    # URLs come from catalog metadata that anyone can upload to (archive.org), so
    # only plain web links get rendered as links — never javascript: or data: URLs.
    if not url or not url.strip().lower().startswith(("http://", "https://")):
        return chip(text, None, kind)
    return (f'<a class="chip {kind} chip-link" href="{html.escape(url.strip(), quote=True)}" '
            f'target="_blank" rel="noopener">{html.escape(text)} ↗</a>')


def display_name(path: str | Path) -> str:
    """'Artist — Title' from the download's credits when known, else from the filename."""
    credit = credits.lookup(path)
    if credit and credit.get("artist") and credit.get("title"):
        return f"{credit['artist']} — {tidy_title(credit['artist'], credit['title'])}"
    return file_display_name(path)


def cue_title(cue: dict) -> str:
    credit = cue.get("credit") or {}
    if credit.get("artist") and credit.get("title"):
        return f"{credit['artist']} — {tidy_title(credit['artist'], credit['title'])}"
    return cue.get("title", "")


def vinyl_badge(name: str) -> str:
    """A tiny record whose label colour is stable per track — it spins on hover."""
    # md5, not hash(): Python salts str hashes per process, so colours would change on restart
    hue = int(hashlib.md5(name.encode()).hexdigest()[:8], 16) % 360
    return f'<span class="vinyl" style="--h:{hue}"></span>'


def chips(items: list[str]) -> str:
    return f'<div>{"".join(items)}</div>'


def compat_label(score: float) -> tuple[str, str]:
    """(human label, css class) for a transition cost."""
    for limit, label, css in COMPAT_BANDS:
        if score < limit:
            return label, css
    return "Rough", "chip-bad"


def track_chips(track: TrackAnalysis, *, extra: list[str] | None = None) -> str:
    items = [
        chip("BPM", f"{track.bpm:.1f}", "chip-bpm"),
        chip("Key", track.camelot or "—", "chip-key"),
        chip("", fmt_duration(track.duration), "chip-muted"),
    ]
    intro, outro = track.first_intro(), track.last_outro()
    bar = 4 * 60 / track.bpm if track.bpm else 2.0
    # No label isn't fatal — the planner falls back to the edge bars — so amber, not red.
    auto = f"auto · {FALLBACK_EDGE_BARS} bars"
    items.append(chip("Intro", f"{intro.duration / bar:.0f} bars" if intro else auto,
                      "chip-good" if intro else "chip-ok"))
    items.append(chip("Outro", f"{outro.duration / bar:.0f} bars" if outro else auto,
                      "chip-good" if outro else "chip-ok"))
    if track.stems_dir:
        items.append(chip("Stems", "✓", "chip-good"))
    else:
        items.append(chip("Stems", "missing", "chip-bad"))
    return chips(items + (extra or []))


# ----------------------------------------------------------------- waveform


def _section_at(times: np.ndarray, track: TrackAnalysis) -> list[str]:
    """Label each sample time with the section it falls inside."""
    if not track.segments:
        return ["inst"] * len(times)
    bounds = np.array([s.start for s in track.segments])
    idx = np.clip(np.searchsorted(bounds, times, side="right") - 1, 0, len(track.segments) - 1)
    return [track.segments[i].label for i in idx]


def waveform_fig(track: TrackAnalysis, peaks: list[float], *,
                 height: int = 150, mix_points: bool = True) -> go.Figure:
    """Mirrored waveform tinted by section, with a labelled section strip beneath."""
    n = len(peaks)
    times = np.linspace(0, track.duration, n)
    amp = np.asarray(peaks, dtype=np.float32)
    labels = _section_at(times, track)
    colors = [theme.SECTION_COLORS.get(l, theme.MUTED) for l in labels]

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        row_heights=[0.76, 0.24], vertical_spacing=0.06)

    width = track.duration / max(n, 1)
    fig.add_trace(go.Bar(
        x=times, y=amp * 2, base=-amp, width=width,
        marker=dict(color=colors, line=dict(width=0)),
        customdata=labels,
        hovertemplate="%{customdata} · %{x:.1f}s<extra></extra>",
    ), row=1, col=1)

    # Section strip drawn as shapes, so the figure-wide `barmode` only ever has to
    # serve the waveform trace above.
    bar_len = 4 * 60 / track.bpm if track.bpm else 2.0
    for seg in track.segments:
        color = theme.SECTION_COLORS.get(seg.label, theme.MUTED)
        fig.add_shape(type="rect", x0=seg.start, x1=seg.end, y0=0.18, y1=0.82,
                      fillcolor=color, line=dict(color=theme.BG, width=1),
                      layer="above", row=2, col=1)
        # Label only bands wide enough to read; the bar count needs more room still.
        # Colour, the legend and hover carry the rest, so narrow bands stay unlabelled.
        share = seg.duration / track.duration if track.duration else 0
        if share > 0.09:
            text = (f"{seg.label} · {seg.duration / bar_len:.0f}" if share > 0.16
                    else seg.label)
            fig.add_annotation(
                x=(seg.start + seg.end) / 2, y=0.5,
                text=text,
                showarrow=False, font=dict(color=theme.BG, size=9.5, weight="bold"),
                row=2, col=1,
            )

    if mix_points:
        # Mark where the planner will actually mix, including its fallback windows.
        out_label = "mix out" if track.last_outro() else "mix out (auto)"
        in_label = "intro ends" if track.first_intro() else "intro ends (auto)"
        _mark(fig, outro_window(track)[0], out_label, theme.RED)
        _mark(fig, intro_window(track)[1], in_label, theme.CYAN)

    theme.style_fig(fig, height)
    # headroom so the "mix out" / "intro ends" annotations aren't cropped
    fig.update_layout(margin=dict(l=0, r=6, t=20, b=4))
    fig.update_xaxes(visible=False, row=1, col=1, range=[0, track.duration])
    fig.update_xaxes(visible=True, row=2, col=1, title=None,
                     range=[0, track.duration], ticksuffix="s")
    fig.update_yaxes(range=[0, 1], row=2, col=1)
    return fig


def _mark(fig: go.Figure, x: float, label: str, color: str) -> None:
    fig.add_vline(x=x, line=dict(color=color, width=1.5, dash="dot"),
                  annotation_text=label, annotation_position="top",
                  annotation_font=dict(color=color, size=10), row=1, col=1)


def section_legend() -> str:
    """Chips explaining the waveform colours."""
    order = ["intro", "verse", "chorus", "break", "bridge", "solo", "inst", "outro"]
    return chips([
        f'<span class="chip" style="border-color:{theme.SECTION_COLORS[k]}44;'
        f'color:{theme.SECTION_COLORS[k]}">{k}</span>' for k in order
    ])


# --------------------------------------------------------------- transition


def _stem_envelopes(n: int) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """(outgoing A gain, incoming B gain) per stem — mirrors transition.render_transition."""
    fade_out = audio_mod.equal_power_fade(n, fade_in=False)
    fade_in = audio_mod.equal_power_fade(n, fade_in=True)

    swap = int(n * BASS_SWAP_PROGRESS)
    bass_a = np.concatenate([np.ones(swap), np.zeros(n - swap)])
    voc = int(n * VOCAL_HANDOFF_PROGRESS)
    vox_a = np.concatenate([np.ones(voc), np.zeros(n - voc)])

    return {
        "drums": (fade_out, fade_in),
        "bass": (bass_a, 1.0 - bass_a),
        "vocals": (vox_a, 1.0 - vox_a),
        "other": (fade_out, fade_in),
    }


def transition_fig(plan: TransitionPlan, height: int = 230) -> go.Figure:
    """Per-stem gain lanes across the transition — what the renderer actually does."""
    n = 400
    bars = np.linspace(0, plan.transition_bars, n)
    envelopes = _stem_envelopes(n)

    lanes = ["drums", "bass", "vocals", "other"]
    fig = go.Figure()

    for row, stem in enumerate(lanes):
        base = len(lanes) - 1 - row          # top lane = drums
        a_gain, b_gain = envelopes[stem]
        color = theme.STEM_COLORS[stem]

        # Invisible floor at this lane's baseline. The next trace fills down to it,
        # so each lane's shading stays inside its own band instead of flooding the
        # chart to y=0 (which "tozeroy" would do).
        fig.add_trace(go.Scatter(
            x=bars, y=np.full(n, float(base)), mode="lines",
            line=dict(color=theme.BORDER, width=1),
            hoverinfo="skip", showlegend=False,
        ))
        fig.add_trace(go.Scatter(
            x=bars, y=base + a_gain * 0.78, mode="lines",
            line=dict(color=color, width=1.6, dash="dot"),
            fill="tonexty", fillcolor=_rgba(color, 0.13),
            name=f"{stem} · out",
            hovertemplate=f"<b>{stem}</b> outgoing %{{y:.2f}}<extra></extra>",
        ))
        fig.add_trace(go.Scatter(
            x=bars, y=base + b_gain * 0.78, mode="lines",
            line=dict(color=color, width=2.4),
            name=f"{stem} · in",
            hovertemplate=f"<b>{stem}</b> incoming %{{y:.2f}}<extra></extra>",
        ))
        fig.add_annotation(x=0, y=base + 0.4, text=stem, showarrow=False,
                           xanchor="right", xshift=-8,
                           font=dict(color=color, size=11))

    swap_bar = plan.transition_bars * BASS_SWAP_PROGRESS
    fig.add_vline(x=swap_bar, line=dict(color=theme.MUTED, width=1, dash="dash"),
                  annotation_text="bass + vocal swap", annotation_position="top",
                  annotation_font=dict(color=theme.MUTED, size=10))

    theme.style_fig(fig, height)
    fig.update_layout(margin=dict(l=60, r=8, t=22, b=24))
    fig.update_xaxes(visible=True, title=dict(text="bars into transition",
                                              font=dict(size=10, color=theme.MUTED)),
                     range=[0, plan.transition_bars])
    fig.update_yaxes(range=[-0.1, len(lanes)])
    return fig


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


def transition_summary(a: TrackAnalysis, b: TrackAnalysis,
                       plan: TransitionPlan) -> str:
    """Chip row describing one A→B move."""
    label, css = compat_label(plan.score)
    bpm_pct = abs(a.bpm - b.bpm) / a.bpm * 100
    stretch = plan.common_bpm / a.bpm
    return chips([
        chip("", label, css),
        chip("Length", f"{plan.transition_bars} bars", "chip-muted"),
        chip("Tempo", f"{a.bpm:.1f} → {plan.common_bpm:.1f}", "chip-bpm"),
        chip("Stretch on A", f"{(stretch - 1) * 100:+.1f}%",
             "chip-good" if bpm_pct <= 6 else "chip-bad"),
        chip("Key", f"{a.camelot or '?'} → {b.camelot or '?'}", "chip-key"),
        chip("Mix out at", fmt_duration(plan.a_transition_start), "chip-muted"),
    ])


def score_detail(breakdown: dict[str, float]) -> str:
    if not breakdown:
        return ""
    parts = [chip(k, f"{v:.2f}", "chip-muted") for k, v in sorted(breakdown.items())
             if abs(v) > 1e-6]
    return chips(parts) if parts else chip("perfect match", None, "chip-good")


