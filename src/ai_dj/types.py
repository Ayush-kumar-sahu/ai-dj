from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

#: Mirrors allin1's HARMONIX_LABELS. "break" is the breakdown — near-universal in dance music.
SegmentLabel = Literal["start", "intro", "verse", "chorus", "break", "bridge", "inst", "solo",
                       "outro", "end"]


class Segment(BaseModel):
    start: float
    end: float
    label: SegmentLabel

    @property
    def duration(self) -> float:
        return self.end - self.start


class TrackAnalysis(BaseModel):
    """Cached analysis for one audio file. Persisted as JSON next to the source."""

    path: str
    sr: int
    duration: float
    bpm: float
    beats: list[float]
    downbeats: list[float]
    segments: list[Segment]

    camelot: str | None = None
    key_confidence: float | None = None

    rms_per_segment: dict[str, float] = Field(default_factory=dict)
    centroid_per_segment: dict[str, float] = Field(default_factory=dict)

    stems_dir: str | None = None

    def segments_by_label(self, label: SegmentLabel) -> list[Segment]:
        return [s for s in self.segments if s.label == label]

    def first_intro(self) -> Segment | None:
        intros = self.segments_by_label("intro")
        return intros[0] if intros else None

    def last_outro(self) -> Segment | None:
        outros = self.segments_by_label("outro")
        return outros[-1] if outros else None

    def downbeats_in(self, start: float, end: float) -> list[float]:
        return [d for d in self.downbeats if start <= d < end]


class TransitionPlan(BaseModel):
    track_a_path: str
    track_b_path: str

    a_transition_start: float
    a_transition_end: float
    b_transition_start: float
    b_transition_end: float

    transition_bars: int
    common_bpm: float
    a_stretch_curve: list[float]

    score: float
    score_breakdown: dict[str, float]

    def __repr__(self) -> str:
        return (
            f"TransitionPlan({Path(self.track_a_path).stem} → {Path(self.track_b_path).stem}, "
            f"{self.transition_bars} bars @ {self.common_bpm:.1f} BPM, score={self.score:.2f})"
        )
