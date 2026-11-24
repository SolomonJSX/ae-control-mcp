"""Immutable domain models for 2D/composition geometry and spatial analysis."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Point2D:
    x: float
    y: float


@dataclass(frozen=True)
class Rect:
    left: float
    top: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.left + self.width

    @property
    def bottom(self) -> float:
        return self.top + self.height

    @property
    def center(self) -> Point2D:
        return Point2D(self.left + self.width / 2.0, self.top + self.height / 2.0)

    @property
    def area(self) -> float:
        return max(0.0, self.width) * max(0.0, self.height)

    def contains_rect(self, other: Rect) -> bool:
        return (
            other.left >= self.left
            and other.top >= self.top
            and other.right <= self.right
            and other.bottom <= self.bottom
        )

    def intersection(self, other: Rect) -> Rect | None:
        x1 = max(self.left, other.left)
        y1 = max(self.top, other.top)
        x2 = min(self.right, other.right)
        y2 = min(self.bottom, other.bottom)
        if x2 <= x1 or y2 <= y1:
            return None
        return Rect(left=x1, top=y1, width=x2 - x1, height=y2 - y1)

    def intersects(self, other: Rect) -> bool:
        return self.intersection(other) is not None


@dataclass(frozen=True)
class LayerGeometry:
    index: int
    name: str
    enabled: bool
    bounds: Rect
    position: Point2D
    scale_percent: Point2D
    rotation_deg: float
    is_text: bool = False
    is_three_d: bool = False
    parent_index: int | None = None
    text_color: tuple[float, float, float] | None = None


@dataclass(frozen=True)
class CompositionGeometry:
    name: str
    width: int
    height: int
    time_seconds: float
    frame_rate: float
    layers: tuple[LayerGeometry, ...]

    @property
    def frame_rect(self) -> Rect:
        return Rect(left=0.0, top=0.0, width=float(self.width), height=float(self.height))

    @property
    def is_vertical(self) -> bool:
        return self.height > self.width

    def safe_rect(self, margin_ratio: float) -> Rect:
        """Return an inset rectangle (e.g. 0.10 margin_ratio -> 80% title-safe)."""
        dx = self.width * margin_ratio
        dy = self.height * margin_ratio
        return Rect(
            left=dx,
            top=dy,
            width=max(0.0, self.width - 2.0 * dx),
            height=max(0.0, self.height - 2.0 * dy),
        )


@dataclass(frozen=True)
class SpatialFinding:
    rule: str
    severity: str  # "info" | "warning" | "error"
    code: str
    message: str
    layers: tuple[str, ...]
    details: dict[str, Any]


@dataclass(frozen=True)
class LayoutReport:
    composition_name: str
    width: int
    height: int
    time_seconds: float
    layer_count: int
    findings: tuple[SpatialFinding, ...]
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MotionFindingInterval:
    rule: str
    severity: str
    code: str
    layers: tuple[str, ...]
    first_time: float
    last_time: float
    sample_count: int
    message: str


@dataclass(frozen=True)
class MotionLayoutReport:
    composition_name: str
    width: int
    height: int
    sampled_times: tuple[float, ...]
    intervals: tuple[MotionFindingInterval, ...]
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
