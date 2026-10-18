"""Demucs 4-stem separation: drums, bass, vocals, other."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

STEM_NAMES = ("drums", "bass", "vocals", "other")


def separate(audio_path: Path, out_dir: Path, model: str = "htdemucs") -> dict[str, Path]:
    """Run Demucs and return {stem_name: wav_path}. Skips if outputs already exist."""
    expected = {name: out_dir / f"{name}.wav" for name in STEM_NAMES}
    if all(p.exists() for p in expected.values()):
        return expected

    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, "-m", "demucs",
        "-n", model,
        "-o", str(out_dir),
        "--filename", "{stem}.{ext}",
        str(audio_path),
    ]
    subprocess.run(cmd, check=True)

    # Demucs nests output under <out_dir>/<model>/<track>/, flatten it.
    nested = out_dir / model / audio_path.stem
    if nested.exists():
        for stem_file in nested.glob("*.wav"):
            stem_file.rename(out_dir / stem_file.name)
        nested.rmdir()
        (out_dir / model).rmdir()

    return expected
