"""Unit tests for parent-aware AE geometry, presets, contrast, and motion timeline rules."""

from __future__ import annotations

import unittest
from typing import Any

from PIL import Image

from ae_control_mcp.ae_geometry import (
    AfterEffectsGeometryProvider,
    _build_geometry_script,
    _build_multi_time_geometry_script,
)
from ae_control_mcp.es3_linter import lint_es3_script_detailed
from ae_control_mcp.geometry import (
    AlignmentConsistencyRule,
    BoundsCheckRule,
    CompositeLayoutAnalyzer,
    CompositionGeometry,
    ContrastReadabilityRule,
    LayerGeometry,
    OverlapCheckRule,
    Point2D,
    Rect,
    SafeZoneRule,
    SocialSafeZoneRule,
    analyze_motion_sequence,
)


class FakeScriptRunner:
    """In-memory ScriptRunner stub for testing without After Effects installed."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.last_script: str | None = None

    def run(self, script_code: str, timeout_seconds: float = 15.0) -> dict[str, Any]:
        self.last_script = script_code
        return self.payload


def _make_layer(
    index: int,
    name: str,
    left: float,
    top: float,
    width: float,
    height: float,
    *,
    enabled: bool = True,
    is_text: bool = False,
    text_color: tuple[float, float, float] | None = None,
) -> LayerGeometry:
    return LayerGeometry(
        index=index,
        name=name,
        enabled=enabled,
        bounds=Rect(left=left, top=top, width=width, height=height),
        position=Point2D(left + width / 2.0, top + height / 2.0),
        scale_percent=Point2D(100.0, 100.0),
        rotation_deg=0.0,
        is_text=is_text,
        text_color=text_color,
    )


class TestGeometryAndRules(unittest.TestCase):
    def test_geometry_extendscript_templates_are_parent_aware_and_pure_es3(self) -> None:
        single = _build_geometry_script("Main", 1.0)
        multi = _build_multi_time_geometry_script("Main", [0.0, 0.5, 1.0], sample_count=3)
        self.assertIn("cur.parent", single)
        self.assertIn("__layerPointToComp", single)
        self.assertEqual(lint_es3_script_detailed(single), [])
        self.assertEqual(lint_es3_script_detailed(multi), [])

    def test_bounds_check_detects_out_of_frame_and_clipped(self) -> None:
        comp = CompositionGeometry(
            name="Main",
            width=1920,
            height=1080,
            time_seconds=0.0,
            frame_rate=30.0,
            layers=(
                _make_layer(1, "Inside", 300, 300, 200, 100),
                _make_layer(2, "Clipped", -50, 100, 300, 200),
                _make_layer(3, "Outside", 2100, 100, 200, 200),
            ),
        )
        findings = BoundsCheckRule().evaluate(comp)
        codes = {f.layers[0]: f.code for f in findings}
        self.assertEqual(codes, {"Clipped": "CLIPPED_BY_FRAME", "Outside": "OUT_OF_FRAME"})

    def test_safe_zone_flags_text_near_edge(self) -> None:
        comp = CompositionGeometry(
            name="Main",
            width=1920,
            height=1080,
            time_seconds=0.0,
            frame_rate=30.0,
            layers=(
                _make_layer(1, "Title", 50, 200, 400, 80, is_text=True),
                _make_layer(2, "SafeTitle", 400, 300, 400, 80, is_text=True),
            ),
        )
        findings = SafeZoneRule(title_margin_ratio=0.10).evaluate(comp)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].code, "OUTSIDE_TITLE_SAFE")

    def test_social_safe_zone_flags_reels_hud_collisions(self) -> None:
        comp = CompositionGeometry(
            name="Reels_9x16",
            width=1080,
            height=1920,
            time_seconds=0.0,
            frame_rate=30.0,
            layers=(
                _make_layer(1, "SafeCenter", 180, 600, 600, 120, is_text=True),
                _make_layer(2, "BottomSub", 180, 1650, 700, 100, is_text=True),
                _make_layer(3, "RightSideTag", 920, 900, 140, 80, is_text=True),
            ),
        )
        findings = SocialSafeZoneRule().evaluate(comp)
        by_layer = {f.layers[0]: f.details["obstructed_zones"] for f in findings}
        self.assertNotIn("SafeCenter", by_layer)
        self.assertIn("bottom_caption_ui", by_layer["BottomSub"])
        self.assertIn("right_action_buttons", by_layer["RightSideTag"])

    def test_alignment_consistency_detects_near_center_and_left_edge_drift(self) -> None:
        comp = CompositionGeometry(
            name="Promo",
            width=1920,
            height=1080,
            time_seconds=0.0,
            frame_rate=30.0,
            layers=(
                # Center is at 665 + 300 = 965 (+5px off 960)
                _make_layer(1, "Headline", 665, 300, 600, 80, is_text=True),
                # Left edge 669 vs 665 (+4px drift)
                _make_layer(2, "Subhead", 669, 420, 400, 50, is_text=True),
            ),
        )
        findings = AlignmentConsistencyRule().evaluate(comp)
        codes = {f.code for f in findings}
        self.assertIn("NEAR_CENTER_MISALIGNMENT", codes)
        self.assertIn("NEAR_LEFT_EDGE_MISALIGNMENT", codes)

    def test_contrast_readability_detects_low_contrast_text(self) -> None:
        light_bg = Image.new("RGB", (640, 360), color=(240, 240, 240))
        dark_bg = Image.new("RGB", (640, 360), color=(18, 22, 30))
        comp = CompositionGeometry(
            name="ContrastComp",
            width=1920,
            height=1080,
            time_seconds=0.0,
            frame_rate=30.0,
            layers=(
                _make_layer(
                    1,
                    "WhiteHeadline",
                    400,
                    400,
                    600,
                    120,
                    is_text=True,
                    text_color=(1.0, 1.0, 1.0),
                ),
            ),
        )
        bad = ContrastReadabilityRule(light_bg).evaluate(comp)
        good = ContrastReadabilityRule(dark_bg).evaluate(comp)
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0].code, "LOW_TEXT_CONTRAST")
        self.assertEqual(good, [])

    def test_motion_sequence_groups_recurring_findings_across_time(self) -> None:
        snap0 = CompositionGeometry(
            name="Anim",
            width=1920,
            height=1080,
            time_seconds=0.0,
            frame_rate=30.0,
            layers=(_make_layer(1, "FlyIn", -300, 400, 200, 100),),
        )
        snap1 = CompositionGeometry(
            name="Anim",
            width=1920,
            height=1080,
            time_seconds=0.5,
            frame_rate=30.0,
            layers=(_make_layer(1, "FlyIn", -120, 400, 100, 100),),
        )
        snap2 = CompositionGeometry(
            name="Anim",
            width=1920,
            height=1080,
            time_seconds=1.0,
            frame_rate=30.0,
            layers=(_make_layer(1, "FlyIn", 500, 400, 200, 100),),
        )
        report = analyze_motion_sequence([snap0, snap1, snap2])
        self.assertEqual(len(report.intervals), 1)
        interval = report.intervals[0]
        self.assertEqual(interval.code, "OUT_OF_FRAME")
        self.assertEqual(interval.first_time, 0.0)
        self.assertEqual(interval.last_time, 0.5)
        self.assertEqual(interval.sample_count, 2)

    def test_overlap_and_provider_with_fake_runner(self) -> None:
        runner = FakeScriptRunner(
            {
                "ok": True,
                "result": {
                    "name": "Intro",
                    "width": 1920,
                    "height": 1080,
                    "timeSeconds": 1.5,
                    "frameRate": 30.0,
                    "layers": [
                        {
                            "index": 1,
                            "name": "Headline",
                            "enabled": True,
                            "isText": True,
                            "isThreeD": False,
                            "parentIndex": 2,
                            "textColor": [1.0, 1.0, 1.0],
                            "position": [960, 540],
                            "scale": [100, 100],
                            "rotation": 0,
                            "bounds": {"left": 660, "top": 490, "width": 600, "height": 100},
                        }
                    ],
                },
            }
        )
        provider = AfterEffectsGeometryProvider(runner)
        comp = provider.get_composition_geometry("Intro", time_seconds=1.5)
        report = CompositeLayoutAnalyzer().analyze(comp)
        self.assertEqual(comp.layers[0].parent_index, 2)
        self.assertEqual(comp.layers[0].text_color, (1.0, 1.0, 1.0))
        self.assertEqual(len(report.findings), 0)
        self.assertEqual( len(OverlapCheckRule().evaluate(comp)), 0 )


if __name__ == "__main__":
    unittest.main()
