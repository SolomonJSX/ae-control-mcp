"""SOLID layout rules and composite spatial analyzer."""

from __future__ import annotations

from collections.abc import Sequence

from ..protocols import LayoutRule
from .models import CompositionGeometry, LayerGeometry, LayoutReport, Rect, SpatialFinding


def _clipped_edges(frame: Rect, target: Rect) -> list[str]:
    edges: list[str] = []
    if target.left < frame.left:
        edges.append("left")
    if target.top < frame.top:
        edges.append("top")
    if target.right > frame.right:
        edges.append("right")
    if target.bottom > frame.bottom:
        edges.append("bottom")
    return edges


class BoundsCheckRule:
    """Detects visible layers that are outside or clipped by the composition frame."""

    @property
    def name(self) -> str:
        return "bounds_check"

    def evaluate(self, comp: CompositionGeometry) -> list[SpatialFinding]:
        frame = comp.frame_rect
        findings: list[SpatialFinding] = []
        for layer in comp.layers:
            if not layer.enabled or layer.bounds.area <= 0:
                continue
            if not frame.intersects(layer.bounds):
                findings.append(
                    SpatialFinding(
                        rule=self.name,
                        severity="error",
                        code="OUT_OF_FRAME",
                        message=(
                            f"Layer '{layer.name}' (#{layer.index}) is completely outside "
                            f"the {comp.width}x{comp.height} composition frame."
                        ),
                        layers=(layer.name,),
                        details={
                            "layer_index": layer.index,
                            "bounds": {
                                "left": round(layer.bounds.left, 2),
                                "top": round(layer.bounds.top, 2),
                                "right": round(layer.bounds.right, 2),
                                "bottom": round(layer.bounds.bottom, 2),
                            },
                        },
                    )
                )
            elif not frame.contains_rect(layer.bounds):
                edges = _clipped_edges(frame, layer.bounds)
                findings.append(
                    SpatialFinding(
                        rule=self.name,
                        severity="warning",
                        code="CLIPPED_BY_FRAME",
                        message=(
                            f"Layer '{layer.name}' (#{layer.index}) is clipped on "
                            f"edge(s): {', '.join(edges)}."
                        ),
                        layers=(layer.name,),
                        details={"layer_index": layer.index, "clipped_edges": edges},
                    )
                )
        return findings


class SafeZoneRule:
    """Checks whether text layers sit within the broadcast/UI title-safe zone."""

    def __init__(self, title_margin_ratio: float = 0.10) -> None:
        self._title_margin_ratio = title_margin_ratio

    @property
    def name(self) -> str:
        return "safe_zone"

    def evaluate(self, comp: CompositionGeometry) -> list[SpatialFinding]:
        frame = comp.frame_rect
        safe = comp.safe_rect(self._title_margin_ratio)
        findings: list[SpatialFinding] = []
        for layer in comp.layers:
            if not layer.enabled or not layer.is_text or layer.bounds.area <= 0:
                continue
            if frame.contains_rect(layer.bounds) and not safe.contains_rect(layer.bounds):
                edges = _clipped_edges(safe, layer.bounds)
                findings.append(
                    SpatialFinding(
                        rule=self.name,
                        severity="warning",
                        code="OUTSIDE_TITLE_SAFE",
                        message=(
                            f"Text layer '{layer.name}' (#{layer.index}) extends outside the "
                            f"title-safe margin on: {', '.join(edges)}."
                        ),
                        layers=(layer.name,),
                        details={
                            "layer_index": layer.index,
                            "margin_ratio": self._title_margin_ratio,
                            "exceeded_edges": edges,
                        },
                    )
                )
        return findings


class OverlapCheckRule:
    """Detects significant overlaps between visible layers."""

    def __init__(self, min_overlap_ratio: float = 0.15) -> None:
        self._min_overlap_ratio = min_overlap_ratio

    @property
    def name(self) -> str:
        return "overlap_check"

    def evaluate(self, comp: CompositionGeometry) -> list[SpatialFinding]:
        visible: list[LayerGeometry] = [
            lyr for lyr in comp.layers if lyr.enabled and lyr.bounds.area > 0
        ]
        findings: list[SpatialFinding] = []
        for i in range(len(visible)):
            a = visible[i]
            for j in range(i + 1, len(visible)):
                b = visible[j]
                inter = a.bounds.intersection(b.bounds)
                if inter is None:
                    continue
                min_area = min(a.bounds.area, b.bounds.area)
                ratio = inter.area / min_area if min_area > 0 else 0.0
                if ratio >= self._min_overlap_ratio:
                    findings.append(
                        SpatialFinding(
                            rule=self.name,
                            severity="info",
                            code="LAYER_OVERLAP",
                            message=(
                                f"Layers '{a.name}' (#{a.index}) and '{b.name}' (#{b.index}) "
                                f"overlap by {ratio:.0%} of the smaller layer's area."
                            ),
                            layers=(a.name, b.name),
                            details={
                                "overlap_ratio": round(ratio, 3),
                                "intersection": {
                                    "left": round(inter.left, 2),
                                    "top": round(inter.top, 2),
                                    "width": round(inter.width, 2),
                                    "height": round(inter.height, 2),
                                },
                            },
                        )
                    )
        return findings


class CompositeLayoutAnalyzer:
    """Aggregates open-ended LayoutRule instances into a single LayoutReport."""

    def __init__(self, rules: Sequence[LayoutRule] | None = None) -> None:
        self._rules: tuple[LayoutRule, ...] = (
            tuple(rules)
            if rules is not None
            else (BoundsCheckRule(), SafeZoneRule(), OverlapCheckRule())
        )

    def analyze(self, comp: CompositionGeometry) -> LayoutReport:
        all_findings: list[SpatialFinding] = []
        for rule in self._rules:
            all_findings.extend(rule.evaluate(comp))

        summary = self._build_summary(comp, all_findings)
        return LayoutReport(
            composition_name=comp.name,
            width=comp.width,
            height=comp.height,
            time_seconds=comp.time_seconds,
            layer_count=len(comp.layers),
            findings=tuple(all_findings),
            summary=summary,
        )

    @staticmethod
    def _build_summary(comp: CompositionGeometry, findings: list[SpatialFinding]) -> str:
        if not findings:
            return (
                f"Layout OK: '{comp.name}' ({comp.width}x{comp.height}) has no spatial "
                f"issues across {len(comp.layers)} layer(s)."
            )
        errors = sum(1 for f in findings if f.severity == "error")
        warnings = sum(1 for f in findings if f.severity == "warning")
        infos = sum(1 for f in findings if f.severity == "info")
        return (
            f"Layout check for '{comp.name}' ({comp.width}x{comp.height}): "
            f"{errors} error(s), {warnings} warning(s), {infos} info finding(s) "
            f"across {len(comp.layers)} layer(s)."
        )
