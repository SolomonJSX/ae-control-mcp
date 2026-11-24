"""SOLID layout rules, preset builders, contrast checking, and motion timeline analyzer."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from PIL import Image

from ..protocols import LayoutRule
from .models import (
    CompositionGeometry,
    LayerGeometry,
    LayoutReport,
    MotionFindingInterval,
    MotionLayoutReport,
    Rect,
    SpatialFinding,
)

LayoutPreset = Literal["standard", "social_vertical", "full"]


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


class SocialSafeZoneRule:
    """Checks vertical Reels / TikTok / YouTube Shorts UI dead-zones for text obstruction."""

    def __init__(
        self,
        top_ratio: float = 0.08,
        bottom_ratio: float = 0.22,
        right_sidebar_ratio: float = 0.16,
        right_sidebar_top_start: float = 0.35,
    ) -> None:
        self._top_ratio = top_ratio
        self._bottom_ratio = bottom_ratio
        self._right_sidebar_ratio = right_sidebar_ratio
        self._right_sidebar_top_start = right_sidebar_top_start

    @property
    def name(self) -> str:
        return "social_safe_zone"

    def evaluate(self, comp: CompositionGeometry) -> list[SpatialFinding]:
        findings: list[SpatialFinding] = []
        top_zone = Rect(0.0, 0.0, float(comp.width), comp.height * self._top_ratio)
        bottom_zone = Rect(
            0.0,
            comp.height * (1.0 - self._bottom_ratio),
            float(comp.width),
            comp.height * self._bottom_ratio,
        )
        right_zone = Rect(
            comp.width * (1.0 - self._right_sidebar_ratio),
            comp.height * self._right_sidebar_top_start,
            comp.width * self._right_sidebar_ratio,
            comp.height * (1.0 - self._right_sidebar_top_start),
        )

        for layer in comp.layers:
            if not layer.enabled or not layer.is_text or layer.bounds.area <= 0:
                continue
            hit_zones: list[str] = []
            if layer.bounds.intersects(top_zone):
                hit_zones.append("top_status_bar")
            if layer.bounds.intersects(bottom_zone):
                hit_zones.append("bottom_caption_ui")
            if layer.bounds.intersects(right_zone):
                hit_zones.append("right_action_buttons")

            if hit_zones:
                findings.append(
                    SpatialFinding(
                        rule=self.name,
                        severity="warning",
                        code="SOCIAL_UI_OBSTRUCTION",
                        message=(
                            f"Text layer '{layer.name}' (#{layer.index}) enters social video UI "
                            f"overlay zone(s): {', '.join(hit_zones)}."
                        ),
                        layers=(layer.name,),
                        details={
                            "layer_index": layer.index,
                            "obstructed_zones": hit_zones,
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


class AlignmentConsistencyRule:
    """Flags subtle near-miss alignments (e.g. text off-center by 2-12px)."""

    def __init__(self, min_delta_px: float = 1.5, max_delta_px: float = 12.0) -> None:
        self._min_delta = min_delta_px
        self._max_delta = max_delta_px

    @property
    def name(self) -> str:
        return "alignment_consistency"

    def evaluate(self, comp: CompositionGeometry) -> list[SpatialFinding]:
        findings: list[SpatialFinding] = []
        comp_cx = comp.width / 2.0
        text_layers = [
            lyr for lyr in comp.layers if lyr.enabled and lyr.is_text and lyr.bounds.area > 0
        ]

        for lyr in text_layers:
            dx = lyr.bounds.center.x - comp_cx
            if self._min_delta <= abs(dx) <= self._max_delta:
                findings.append(
                    SpatialFinding(
                        rule=self.name,
                        severity="info",
                        code="NEAR_CENTER_MISALIGNMENT",
                        message=(
                            f"Text layer '{lyr.name}' (#{lyr.index}) is off horizontal center "
                            f"by {dx:+.1f}px (possible unintended offset)."
                        ),
                        layers=(lyr.name,),
                        details={"layer_index": lyr.index, "offset_x_px": round(dx, 2)},
                    )
                )

        for i in range(len(text_layers)):
            a = text_layers[i]
            for j in range(i + 1, len(text_layers)):
                b = text_layers[j]
                left_diff = b.bounds.left - a.bounds.left
                if self._min_delta <= abs(left_diff) <= self._max_delta:
                    findings.append(
                        SpatialFinding(
                            rule=self.name,
                            severity="info",
                            code="NEAR_LEFT_EDGE_MISALIGNMENT",
                            message=(
                                f"Text layers '{a.name}' and '{b.name}' have nearly aligned left "
                                f"edges differing by {abs(left_diff):.1f}px."
                            ),
                            layers=(a.name, b.name),
                            details={"left_delta_px": round(left_diff, 2)},
                        )
                    )
        return findings


def _srgb_channel_to_linear(c: float) -> float:
    c = max(0.0, min(1.0, c))
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(rgb_unit: tuple[float, float, float]) -> float:
    r, g, b = (_srgb_channel_to_linear(ch) for ch in rgb_unit)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def wcag_contrast_ratio(lum_a: float, lum_b: float) -> float:
    lighter = max(lum_a, lum_b)
    darker = min(lum_a, lum_b)
    return (lighter + 0.05) / (darker + 0.05)


class ContrastReadabilityRule:
    """Evaluates WCAG contrast between text layer fill colors and rendered frame pixels."""

    def __init__(self, frame_image: Image.Image, min_contrast_ratio: float = 3.0) -> None:
        self._frame = frame_image.convert("RGB")
        self._min_contrast = min_contrast_ratio

    @property
    def name(self) -> str:
        return "contrast_readability"

    def evaluate(self, comp: CompositionGeometry) -> list[SpatialFinding]:
        if comp.width <= 0 or comp.height <= 0:
            return []
        sx = self._frame.width / float(comp.width)
        sy = self._frame.height / float(comp.height)
        findings: list[SpatialFinding] = []

        for lyr in comp.layers:
            if not lyr.enabled or not lyr.is_text or lyr.bounds.area <= 0 or lyr.text_color is None:
                continue
            clipped = comp.frame_rect.intersection(lyr.bounds)
            if clipped is None or clipped.area <= 0:
                continue

            x1 = max(0, min(self._frame.width - 1, int(round(clipped.left * sx))))
            y1 = max(0, min(self._frame.height - 1, int(round(clipped.top * sy))))
            x2 = max(x1 + 1, min(self._frame.width, int(round(clipped.right * sx))))
            y2 = max(y1 + 1, min(self._frame.height, int(round(clipped.bottom * sy))))

            crop = self._frame.crop((x1, y1, x2, y2))
            # Sample on a small grid to estimate background luminance around/behind glyphs
            thumb = crop.resize((min(16, crop.width), min(16, crop.height)), Image.Resampling.BILINEAR)
            pixel_getter = getattr(thumb, "get_flattened_data", thumb.getdata)
            pixels = list(pixel_getter())
            if not pixels:
                continue

            text_lum = relative_luminance(lyr.text_color)
            # Filter out pixels very close to the text fill color itself so we measure background
            bg_lums: list[float] = []
            tr, tg, tb = (lyr.text_color[0] * 255.0, lyr.text_color[1] * 255.0, lyr.text_color[2] * 255.0)
            for pr, pg, pb in pixels:
                dist_sq = (pr - tr) ** 2 + (pg - tg) ** 2 + (pb - tb) ** 2
                if dist_sq > 900.0:  # > ~30 RGB Euclidean distance from text fill
                    bg_lums.append(relative_luminance((pr / 255.0, pg / 255.0, pb / 255.0)))

            if not bg_lums:
                # Virtually every pixel matches text color -> text blends into identical solid background!
                bg_lum = text_lum
            else:
                bg_lums.sort()
                bg_lum = bg_lums[len(bg_lums) // 2]

            ratio = wcag_contrast_ratio(text_lum, bg_lum)
            if ratio < self._min_contrast:
                findings.append(
                    SpatialFinding(
                        rule=self.name,
                        severity="warning",
                        code="LOW_TEXT_CONTRAST",
                        message=(
                            f"Text layer '{lyr.name}' (#{lyr.index}) has low contrast "
                            f"({ratio:.2f}:1 < {self._min_contrast:.1f}:1) against its background."
                        ),
                        layers=(lyr.name,),
                        details={
                            "layer_index": lyr.index,
                            "contrast_ratio": round(ratio, 2),
                            "min_required": self._min_contrast,
                            "text_color": [round(c, 3) for c in lyr.text_color],
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


def build_analyzer_for_preset(
    preset: LayoutPreset = "standard",
    frame_image: Image.Image | None = None,
    is_vertical_comp: bool = False,
) -> CompositeLayoutAnalyzer:
    """Construct a CompositeLayoutAnalyzer tailored to the requested preset."""
    rules: list[LayoutRule] = [BoundsCheckRule(), SafeZoneRule(), OverlapCheckRule()]
    if preset == "social_vertical" or (preset == "full" and is_vertical_comp):
        rules.append(SocialSafeZoneRule())
    if preset == "full":
        rules.append(AlignmentConsistencyRule())
    if frame_image is not None:
        rules.append(ContrastReadabilityRule(frame_image))
    return CompositeLayoutAnalyzer(rules)


def analyze_motion_sequence(
    samples: Sequence[CompositionGeometry],
    preset: LayoutPreset = "standard",
) -> MotionLayoutReport:
    """Evaluate layout rules across multiple timeline samples and group recurring issues."""
    if not samples:
        raise ValueError("samples must contain at least one CompositionGeometry snapshot.")

    first = samples[0]
    analyzer = build_analyzer_for_preset(preset=preset, is_vertical_comp=first.is_vertical)
    grouped: dict[tuple[str, str, tuple[str, ...]], dict[str, object]] = {}

    for snap in samples:
        report = analyzer.analyze(snap)
        for finding in report.findings:
            key = (finding.rule, finding.code, finding.layers)
            if key not in grouped:
                grouped[key] = {
                    "rule": finding.rule,
                    "severity": finding.severity,
                    "code": finding.code,
                    "layers": finding.layers,
                    "first_time": snap.time_seconds,
                    "last_time": snap.time_seconds,
                    "sample_count": 1,
                    "message": finding.message,
                }
            else:
                entry = grouped[key]
                entry["first_time"] = min(float(entry["first_time"]), snap.time_seconds)
                entry["last_time"] = max(float(entry["last_time"]), snap.time_seconds)
                entry["sample_count"] = int(entry["sample_count"]) + 1

    intervals = tuple(
        MotionFindingInterval(
            rule=str(v["rule"]),
            severity=str(v["severity"]),
            code=str(v["code"]),
            layers=tuple(v["layers"]),  # type: ignore[arg-type]
            first_time=round(float(v["first_time"]), 3),
            last_time=round(float(v["last_time"]), 3),
            sample_count=int(v["sample_count"]),
            message=str(v["message"]),
        )
        for v in grouped.values()
    )

    sampled_times = tuple(round(s.time_seconds, 3) for s in samples)
    if not intervals:
        summary = (
            f"Motion layout OK: '{first.name}' ({first.width}x{first.height}) passed "
            f"across {len(samples)} sampled timestamp(s)."
        )
    else:
        errors = sum(1 for item in intervals if item.severity == "error")
        warnings = sum(1 for item in intervals if item.severity == "warning")
        infos = sum(1 for item in intervals if item.severity == "info")
        summary = (
            f"Motion layout check for '{first.name}' across {len(samples)} sample(s): "
            f"{errors} error interval(s), {warnings} warning interval(s), {infos} info interval(s)."
        )

    return MotionLayoutReport(
        composition_name=first.name,
        width=first.width,
        height=first.height,
        sampled_times=sampled_times,
        intervals=intervals,
        summary=summary,
    )
