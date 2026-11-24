"""Geometry domain models and SOLID layout analyzers."""

from .analyzers import (
    AlignmentConsistencyRule,
    BoundsCheckRule,
    CompositeLayoutAnalyzer,
    ContrastReadabilityRule,
    LayoutPreset,
    OverlapCheckRule,
    SafeZoneRule,
    SocialSafeZoneRule,
    analyze_motion_sequence,
    build_analyzer_for_preset,
)
from .models import (
    CompositionGeometry,
    LayerGeometry,
    LayoutReport,
    MotionFindingInterval,
    MotionLayoutReport,
    Point2D,
    Rect,
    SpatialFinding,
)

__all__ = [
    "AlignmentConsistencyRule",
    "BoundsCheckRule",
    "CompositeLayoutAnalyzer",
    "CompositionGeometry",
    "ContrastReadabilityRule",
    "LayerGeometry",
    "LayoutPreset",
    "LayoutReport",
    "MotionFindingInterval",
    "MotionLayoutReport",
    "OverlapCheckRule",
    "Point2D",
    "Rect",
    "SafeZoneRule",
    "SocialSafeZoneRule",
    "SpatialFinding",
    "analyze_motion_sequence",
    "build_analyzer_for_preset",
]
