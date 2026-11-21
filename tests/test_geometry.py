"""Unit tests for SOLID geometry models, layout rules, and AE geometry provider."""

from __future__ import annotations

import unittest
from typing import Any

from ae_control_mcp.ae_geometry import AfterEffectsGeometryProvider
from ae_control_mcp.geometry import (
    BoundsCheckRule,
    CompositeLayoutAnalyzer,
    CompositionGeometry,
    LayerGeometry,
    OverlapCheckRule,
    Point2D,
    Rect,
    SafeZoneRule,
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
    )


class TestGeometryAndRules(unittest.TestCase):
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
        self.assertEqual(findings[0].layers, ("Title",))

    def test_overlap_rule_detects_overlapping_layers(self) -> None:
        comp = CompositionGeometry(
            name="Main",
            width=1920,
            height=1080,
            time_seconds=0.0,
            frame_rate=30.0,
            layers=(
                _make_layer(1, "CardA", 200, 200, 400, 300),
                _make_layer(2, "CardB", 400, 300, 400, 300),
            ),
        )
        findings = OverlapCheckRule(min_overlap_ratio=0.15).evaluate(comp)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].code, "LAYER_OVERLAP")

    def test_provider_with_fake_runner_and_composite_analyzer(self) -> None:
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

        self.assertEqual(comp.name, "Intro")
        self.assertEqual(len(report.findings), 0)
        self.assertIn("Layout OK", report.summary)
        self.assertIsNotNone(runner.last_script)
        assert runner.last_script is not None
        self.assertIn("Math.cos", runner.last_script)
        self.assertIn("activeAtTime", runner.last_script)
        self.assertIn("nullLayer", runner.last_script)


if __name__ == "__main__":
    unittest.main()
