"""Geometry domain models and SOLID layout analyzers."""

from .analyzers import (
    BoundsCheckRule,
    CompositeLayoutAnalyzer,
    OverlapCheckRule,
    SafeZoneRule,
)
from .models import (
    CompositionGeometry,
    LayerGeometry,
    LayoutReport,
    Point2D,
    Rect,
    SpatialFinding,
)

__all__ = [
    "BoundsCheckRule",
    "CompositeLayoutAnalyzer",
    "CompositionGeometry",
    "LayerGeometry",
    "LayoutReport",
    "OverlapCheckRule",
    "Point2D",
    "Rect",
    "SafeZoneRule",
    "SpatialFinding",
]
