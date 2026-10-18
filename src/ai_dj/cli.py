from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from .analysis.analyzer import analyze
from .render import render_queue
from .sources import SourceError
from .sources.jamendo import JamendoSource

console = Console()

SONGS_DIR = Path(__file__).resolve().parents[2] / "data" / "songs"


@click.group()
def main():
    """AI DJ — auto-mix a queue of tracks with stem-aware transitions."""


@main.command()
@click.argument("paths", nargs=-1, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--no-stems", is_flag=True, help="Skip Demucs stem separation (faster, but transition rendering will fail)")
@click.option("--force", is_flag=True, help="Re-run analysis even if cached")
def info(paths: tuple[Path, ...], no_stems: bool, force: bool):
    """Analyze one or more tracks and print BPM/key/sections."""
    for p in paths:
        console.rule(f"[bold]{p.name}[/bold]")
        a = analyze(p, run_stems=not no_stems, force=force)
        console.print(f"BPM: {a.bpm:.2f}    Camelot: {a.camelot or '?'} (conf={a.key_confidence:.2f})")

        t = Table(show_header=True, header_style="bold")
        t.add_column("#"); t.add_column("Label"); t.add_column("Start"); t.add_column("End"); t.add_column("Bars")
        bar = 4 * 60 / a.bpm
        for i, s in enumerate(a.segments):
            t.add_row(str(i), s.label, f"{s.start:.2f}", f"{s.end:.2f}", f"{s.duration / bar:.1f}")
        console.print(t)


@main.command()
@click.argument("paths", nargs=-1, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--out", "-o", type=click.Path(path_type=Path), default=Path("data/output/mix.wav"))
def mix(paths: tuple[Path, ...], out: Path):
    """Mix a sequence of tracks into a single WAV."""
    render_queue(paths, out)


@main.command()
@click.argument("query", nargs=-1)
@click.option("--tag", "-t", multiple=True, help="Genre tag, repeatable (e.g. -t house -t techno)")
@click.option("--speed", type=click.Choice(["verylow", "low", "medium", "high", "veryhigh"]))
@click.option("--limit", "-n", default=15, show_default=True)
@click.option("--client-id", envvar="JAMENDO_CLIENT_ID", help="Or set JAMENDO_CLIENT_ID")
def search(query: tuple[str, ...], tag: tuple[str, ...], speed: str | None,
           limit: int, client_id: str | None):
    """Search Jamendo's Creative Commons catalog."""
    try:
        results = JamendoSource(client_id).search(
            " ".join(query), tags=list(tag), speed=speed, limit=limit)
    except SourceError as e:
        raise click.ClickException(str(e)) from e

    if not results:
        console.print("[yellow]No downloadable tracks matched.[/yellow]")
        return

    t = Table(show_header=True, header_style="bold")
    for col in ("ID", "Artist", "Title", "Len", "Speed", "Licence"):
        t.add_column(col)
    for r in results:
        t.add_row(r.id, r.artist[:26], r.name[:34],
                  f"{int(r.duration // 60)}:{int(r.duration % 60):02d}",
                  r.speed or "—", r.license_name or "—")
    console.print(t)
    console.print(f"\n[dim]Fetch one with:[/dim] aidj fetch {results[0].id}")


@main.command()
@click.argument("track_ids", nargs=-1, required=True)
@click.option("--dest", type=click.Path(path_type=Path), default=SONGS_DIR, show_default=True)
@click.option("--client-id", envvar="JAMENDO_CLIENT_ID", help="Or set JAMENDO_CLIENT_ID")
def fetch(track_ids: tuple[str, ...], dest: Path, client_id: str | None):
    """Download Jamendo tracks by ID into the local library."""
    source = JamendoSource(client_id)
    for tid in track_ids:
        try:
            track = source.get(tid)
        except SourceError as e:
            raise click.ClickException(str(e)) from e
        if track is None:
            console.print(f"[yellow]No track with id {tid}[/yellow]")
            continue
        try:
            path = source.download(track, dest)
        except SourceError as e:
            console.print(f"[red]{e}[/red]")
            continue
        console.print(f"[green]✓[/green] {track.label} → {path}")



@main.command()
@click.option("--tracks", "-n", default=10, show_default=True, help="Songs in the demo set")
@click.option("--candidates", default=20, show_default=True,
              help="How many to audition before keeping the best-matched set")
@click.option("--no-render", is_flag=True, help="Stop after analysis and sequencing")
def demo(tracks: int, candidates: int, no_render: bool):
    """Download a demo set from the Internet Archive, then analyze, sequence and render it."""
    import time as _time

    from .demo import build_demo

    def log(msg: str) -> None:
        console.print(f"[dim]{_time.strftime('%H:%M:%S')}[/dim] {msg}", highlight=False)

    try:
        summary = build_demo(n=tracks, candidates=candidates,
                             render=not no_render, log=log)
    except SourceError as e:
        raise click.ClickException(str(e)) from e
    if summary.get("mp3"):
        console.print(f"\n[green]Demo mix:[/green] {summary['mp3']}")
    console.print("Open the app to explore it:  streamlit run src/ai_dj/web.py")


@main.command("arrange")
@click.argument("set_id")
def arrange_cmd(set_id: str):
    """Analyze, sequence and mix a saved set. The web app runs this in the background."""
    import os
    import sys
    import time as _time
    import traceback

    from . import sets
    from .arrange import arrange

    track_set = sets.load_set(set_id)
    if track_set is None:
        raise click.ClickException(f"No set called {set_id}")
    started = sets.read_status(set_id).started_at or _time.time()
    status = sets.JobStatus(state="running", pid=os.getpid(), stage="starting",
                            started_at=started)
    sets.write_status(set_id, status)

    def log(msg: str) -> None:
        click.echo(f"{_time.strftime('%H:%M:%S')} {msg}")

    last = [0.0]

    def progress(stage: str, frac: float, detail: dict) -> None:
        now = _time.time()
        if stage == status.stage and now - last[0] < 0.75:
            return  # the UI polls every 2 s; no need to rewrite the file faster
        if sets.read_status(set_id).state == "cancelled":
            sys.exit(0)  # the web app cancelled us: don't overwrite that
        last[0] = now
        status.stage, status.progress, status.detail = stage, round(frac, 4), detail
        sets.write_status(set_id, status)

    paths = [SONGS_DIR / n for n in track_set.tracks if (SONGS_DIR / n).exists()]
    missing = [n for n in track_set.tracks if not (SONGS_DIR / n).exists()]
    for n in missing:
        log(f"missing from the library, skipping: {n}")
    try:
        result = arrange(paths, sets.mix_path(set_id), log=log, progress=progress)
    except Exception as e:  # report every failure to the UI, not just expected ones
        log(traceback.format_exc())
        status.state, status.error = "failed", str(e)
        sets.write_status(set_id, status)
        raise SystemExit(1)
    result["missing"] = missing
    status.state, status.stage, status.progress, status.result = "done", "done", 1.0, result
    sets.write_status(set_id, status)
    log(f"Set mixed in {(_time.time() - started) / 60:.1f} min")

if __name__ == "__main__":
    main()
