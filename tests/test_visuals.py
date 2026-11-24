"""Unit tests for visual contact sheets and annotated layout overlays."""

from __future__ import annotations

import io
import unittest

from PIL import Image

from ae_control_mcp import visuals
from ae_control_mcp.geometry import (
    CompositionGeometry,
    LayerGeometry,
    Point2D,
    Rect,
    build_analyzer_for_preset,
)


class TestVisualHelpers(unittest.TestCase):
    def test_annotate_layout_frame_renders_jpeg_overlay(self) -> None:
        frame = Image.new("RGB", (1080, 1920), color=(30, 35, 45))
        comp = CompositionGeometry(
            name="Reels",
            width=1080,
            height=1920,
            time_seconds=0.5,
            frame_rate=30.0,
            layers=(
                LayerGeometry(
                    index=1,
                    name="Caption",
                    enabled=True,
                    bounds=Rect(120, 1680, 800, 110),
                    position=Point2D(520, 1735),
                    scale_percent=Point2D(100, 100),
                    rotation_deg=0.0,
                    is_text=True,
                    text_color=(1.0, 1.0, 1.0),
                ),
            ),
        )
        report = build_analyzer_for_preset("social_vertical", frame_image=frame, is_vertical_comp=True).analyze(comp)
        img_bytes, out_w, out_h = visuals.annotate_layout_frame(
            frame_image=frame,
            comp=comp,
            report=report,
            include_social_zones=True,
            max_dimension=960,
        )
        self.assertEqual(out_h, 960)
        self.assertEqual(out_w, 540)
        with Image.open(io.BytesIO(img_bytes)) as decoded:
            self.assertEqual(decoded.size, (540, 960))

    def test_compose_contact_sheet_stitches_grid(self) -> None:
        frames = [
            (i * 0.5, Image.new("RGB", (640, 360), color=(20 * i, 50, 90)))
            for i in range(6)
        ]
        sheet_bytes, width, height = visuals.compose_contact_sheet(
            frames=frames,
            comp_name="Intro",
            frame_rate=30.0,
            columns=3,
            cell_max_dimension=320,
        )
        self.assertGreater(width, 900)
        self.assertGreater(height, 400)
        with Image.open(io.BytesIO(sheet_bytes)) as decoded:
            self.assertEqual(decoded.size, (width, height))


if __name__ == "__main__":
    unittest.main()
