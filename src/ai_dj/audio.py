"""Audio helpers: stem loading, time-stretch, equal-power curves."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

from .analysis.stems import STEM_NAMES


def load_stems(stems_dir: Path) -> tuple[dict[str, np.ndarray], int]:
    """Load all 4 stems from a Demucs output dir. Returns ({name: samples [N, 2]}, sr)."""
    stems: dict[str, np.ndarray] = {}
    sr = None
    for name in STEM_NAMES:
        # Decode straight to float32: the float64 default is a transient 2x copy per
        # stem, and a transition holds eight stems at once.
        data, file_sr = sf.read(str(stems_dir / f"{name}.wav"), always_2d=True, dtype="float32")
        if sr is None:
            sr = file_sr
        elif file_sr != sr:
            raise ValueError(f"Stem sample rate mismatch: {file_sr} vs {sr}")
        stems[name] = data
    assert sr is not None
    return stems, sr


def time_stretch(samples: np.ndarray, sr: int, factor: float) -> np.ndarray:
    """factor > 1.0 → faster/shorter. Pitch-preserving via librosa phase vocoder.

    Quality is acceptable for ±6% stretches typical in DJ mixing. For better quality,
    swap in pyrubberband once `brew install rubberband` is available.
    """
    if abs(factor - 1.0) < 1e-3:
        return samples
    import librosa
    if samples.ndim == 1:
        return librosa.effects.time_stretch(samples, rate=factor).astype(np.float32)
    # Per-channel stretch then re-stack (librosa expects mono)
    chans = [librosa.effects.time_stretch(samples[:, c], rate=factor) for c in range(samples.shape[1])]
    n = min(c.shape[0] for c in chans)
    return np.stack([c[:n] for c in chans], axis=1).astype(np.float32)


def equal_power_fade(n: int, fade_in: bool) -> np.ndarray:
    """sin/cos curve so A² + B² = 1 across the crossfade."""
    t = np.linspace(0, np.pi / 2, n, dtype=np.float32)
    return np.sin(t) if fade_in else np.cos(t)


def linear_fade(n: int, fade_in: bool) -> np.ndarray:
    return np.linspace(0, 1, n, dtype=np.float32) if fade_in else np.linspace(1, 0, n, dtype=np.float32)


def apply_envelope(samples: np.ndarray, env: np.ndarray) -> np.ndarray:
    """Multiply per-sample envelope across both channels."""
    if samples.ndim == 1:
        return samples * env
    return samples * env[:, None]


def pad_to(samples: np.ndarray, length: int) -> np.ndarray:
    if samples.shape[0] >= length:
        return samples[:length]
    pad = np.zeros((length - samples.shape[0], samples.shape[1]), dtype=samples.dtype)
    return np.concatenate([samples, pad], axis=0)


def encode_mp3(wav_path: Path, mp3_path: Path | None = None,
               block_frames: int = 1 << 18) -> Path:
    """Transcode a rendered mix to VBR MP3 for playback and sharing.

    Works block by block so memory stays flat however long the mix is. The WAV
    stays as the lossless master; the MP3 is ~1/6 the size, which matters when a
    browser has to load a 45-minute set.
    """
    mp3_path = mp3_path or wav_path.with_suffix(".mp3")
    info = sf.info(str(wav_path))
    tmp = mp3_path.with_name(mp3_path.name + ".part")
    with sf.SoundFile(str(tmp), "w", samplerate=info.samplerate, channels=info.channels,
                      format="MP3", subtype="MPEG_LAYER_III",
                      compression_level=0.0,  # libsndfile's best-quality setting
                      bitrate_mode="VARIABLE") as out:
        for block in sf.blocks(str(wav_path), blocksize=block_frames,
                               dtype="float32", always_2d=True):
            out.write(block)
    tmp.replace(mp3_path)
    return mp3_path
