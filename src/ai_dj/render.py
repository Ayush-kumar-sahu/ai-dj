"""Render a queue of tracks → single mix WAV using stem-aware transitions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Iterable

import numpy as np
import soundfile as sf
from rich.console import Console

from . import audio, compatibility
from .analysis.analyzer import analyze
from .sources import credits
from .sources.base import display_name
from .transition import BASS_SWAP_PROGRESS, plan_transition, render_transition
from .types import TrackAnalysis, TransitionPlan

console = Console()

#: Called with (human-readable step, fraction complete 0..1). Lets a UI show progress.
ProgressFn = Callable[[str, float], None]


def render_queue(audio_paths: Iterable[Path], out_path: Path, sr: int = 44100,
                 progress: ProgressFn | None = None) -> Path:
    paths = [Path(p).resolve() for p in audio_paths]
    if len(paths) < 2:
        raise ValueError("Need at least 2 tracks to make a mix")

    def report(msg: str, frac: float) -> None:
        if progress:
            progress(msg, min(max(frac, 0.0), 1.0))

    console.print(f"[bold]Analyzing {len(paths)} tracks...[/bold]")
    tracks = []
    for i, p in enumerate(paths):
        report(f"Loading {display_name(p)}", 0.15 * i / len(paths))
        tracks.append(analyze(p))

    plans = plan_queue(tracks)
    for plan in plans:
        console.print(f"  {plan!r}")
    report("Planned transitions", 0.2)

    return _render(tracks, plans, out_path, sr, report)


def plan_queue(tracks: list[TrackAnalysis]) -> list[TransitionPlan]:
    """Plan every transition in order, chained so no track mixes out before it has
    finished mixing in. Planning pairs independently can make the audio jump back."""
    plans: list[TransitionPlan] = []
    mixed_in_until = 0.0
    for a, b in zip(tracks, tracks[1:]):
        s, breakdown = compatibility.score(a, b)
        plan = plan_transition(a, b, score=s, score_breakdown=breakdown,
                               a_not_before=mixed_in_until)
        plans.append(plan)
        mixed_in_until = plan.b_transition_end
    return plans


def _render(tracks: list[TrackAnalysis], plans: list[TransitionPlan],
            out_path: Path, sr: int, report: ProgressFn | None = None) -> Path:
    steps = max(len(tracks), 1)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cues: list[dict] = [_cue(1, tracks[0], 0, sr)]
    cues[0]["enters_from"] = 0.0
    written = 0  # frames

    # Stream straight to disk. A 10-track set is ~45 min of stereo audio: held as
    # one float32 array, plus the copy np.concatenate makes, that is ~2 GB — enough
    # to push an 8 GB machine into swap. Writing per chunk keeps peak memory at
    # roughly one transition's worth of stems.
    with sf.SoundFile(str(out_path), "w", samplerate=sr, channels=2) as fh:
        for i, track in enumerate(tracks):
            if report:
                report(f"Laying down {display_name(track.path)}", 0.2 + 0.75 * i / steps)
            prev_plan = plans[i - 1] if i > 0 else None
            next_plan = plans[i] if i < len(plans) else None

            head_start = prev_plan.b_transition_end if prev_plan else 0.0
            tail_end = next_plan.a_transition_start if next_plan else track.duration

            cues[i]["solo_start"] = round(written / sr, 2)   # its incoming blend is over
            body = _load_segment(Path(track.path), sr, head_start, tail_end)
            fh.write(body)
            written += body.shape[0]
            cues[i]["solo_end"] = round(written / sr, 2)     # its outgoing blend starts

            if next_plan is not None:
                console.print(f"[dim]Rendering transition {i + 1}/{len(plans)}...[/dim]")
                if report:
                    report(f"Mixing transition {i + 1}/{len(plans)}",
                           0.2 + 0.75 * (i + 0.5) / steps)
                # The next track is audible from the first bar of the transition.
                blend_start = written
                nxt = _cue(i + 2, tracks[i + 1], blend_start, sr)
                nxt["enters_from"] = round(next_plan.b_transition_start, 2)  # in its own timeline
                nxt["blend_bars"] = next_plan.transition_bars
                nxt["tempo_from"] = round(track.bpm, 1)
                cues.append(nxt)
                seg = render_transition(next_plan, track, tracks[i + 1], sr=sr)
                fh.write(seg)
                written += seg.shape[0]
                # The bass hands over mid-blend: that is where the change of track lands.
                nxt["swap"] = round((blend_start + BASS_SWAP_PROGRESS * seg.shape[0]) / sr, 2)
                cues[i]["exits_from"] = round(next_plan.a_transition_start, 2)
            cues[i]["end"] = round(written / sr, 2)              # fully gone from the mix

    if report:
        report("Writing tracklist", 0.98)
    tracklist_path(out_path).write_text(json.dumps(
        {"duration": written / sr, "tracks": cues}, indent=2))
    console.print(f"[green]✓ Wrote {out_path} ({written / sr:.1f}s)[/green]")
    return out_path


def tracklist_path(mix_path: Path) -> Path:
    """Sidecar JSON listing when each track enters the mix."""
    return mix_path.with_name(mix_path.stem + ".tracklist.json")


def load_tracklist(mix_path: Path) -> dict | None:
    try:
        return json.loads(tracklist_path(mix_path).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _cue(number: int, track: TrackAnalysis, frame: int, sr: int) -> dict:
    return {
        "number": number,
        "title": display_name(track.path),
        "start": round(frame / sr, 2),
        "bpm": round(track.bpm, 1),
        "camelot": track.camelot,
        # artist / licence / source for attribution, when the track was downloaded
        "credit": credits.lookup(track.path),
    }


def _load_segment(path: Path, sr: int, start_s: float, end_s: float) -> np.ndarray:
    """Read a stereo slice from disk. Resamples if file SR differs."""
    info = sf.info(str(path))
    file_sr = info.samplerate
    start_frame = int(start_s * file_sr)
    end_frame = int(end_s * file_sr)
    data, _ = sf.read(str(path), start=start_frame, stop=end_frame, always_2d=True, dtype="float32")
    if file_sr != sr:
        import librosa
        data = librosa.resample(data.T, orig_sr=file_sr, target_sr=sr).T
    if data.shape[1] == 1:
        data = np.repeat(data, 2, axis=1)
    return data
