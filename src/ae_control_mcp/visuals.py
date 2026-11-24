"""Visual inspection helpers: annotated layout overlays and multi-frame contact sheets."""

from __future__ import annotations

import io
import math
from collections.abc import Sequence

from PIL import Image, ImageDraw, ImageFont

from .geometry.models import CompositionGeometry, LayoutReport


def _highest_severity_by_layer(report: LayoutReport) -> dict[str, str]:
    rank = {"info": 1, "warning": 2, "error": 3}
    result: dict[str, str] = {}
    for finding in report.findings:
        sev = finding.severity
        for lyr_name in finding.layers:
            prev = result.get(lyr_name)
            if prev is None or rank.get(sev, 0) > rank.get(prev, 0):
                result[lyr_name] = sev
    return result


def annotate_layout_frame(
    frame_image: Image.Image,
    comp: CompositionGeometry,
    report: LayoutReport,
    include_social_zones: bool = False,
    max_dimension: int = 1280,
) -> tuple[bytes, int, int]:
    """Draw safe-zone guides, layer bounding boxes, and severity badges over a frame."""
    base = frame_image.convert("RGBA")
    if max_dimension > 0 and max(base.width, base.height) > max_dimension:
        ratio = max_dimension / float(max(base.width, base.height))
        base = base.resize(
            (
                max(1, int(round(base.width * ratio))),
                max(1, int(round(base.height * ratio))),
            ),
            Image.Resampling.LANCZOS,
        )

    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font = ImageFont.load_default()

    sx = base.width / float(max(1, comp.width))
    sy = base.height / float(max(1, comp.height))

    # Social UI dead-zones (shaded translucent coral/orange)
    if include_social_zones:
        top_h = int(round(base.height * 0.08))
        bot_y = int(round(base.height * 0.78))
        right_x = int(round(base.width * 0.84))
        right_y = int(round(base.height * 0.35))
        draw.rectangle([0, 0, base.width, top_h], fill=(255, 87, 51, 45))
        draw.rectangle([0, bot_y, base.width, base.height], fill=(255, 87, 51, 55))
        draw.rectangle([right_x, right_y, base.width, bot_y], fill=(255, 87, 51, 45))

    # Broadcast 10% Title-Safe guide (cyan outline)
    safe = comp.safe_rect(0.10)
    draw.rectangle(
        [
            int(round(safe.left * sx)),
            int(round(safe.top * sy)),
            int(round(safe.right * sx)),
            int(round(safe.bottom * sy)),
        ],
        outline=(0, 212, 255, 160),
        width=1,
    )

    severity_map = _highest_severity_by_layer(report)
    palette = {
        "error": (255, 68, 68, 235),
        "warning": (255, 193, 7, 235),
        "info": (96, 165, 250, 215),
        "ok": (34, 197, 94, 200),
    }

    for lyr in comp.layers:
        if not lyr.enabled or lyr.bounds.area <= 0:
            continue
        sev = severity_map.get(lyr.name, "ok")
        color = palette.get(sev, palette["ok"])

        x1 = max(0, min(base.width - 1, int(round(lyr.bounds.left * sx))))
        y1 = max(0, min(base.height - 1, int(round(lyr.bounds.top * sy))))
        x2 = max(x1 + 1, min(base.width - 1, int(round(lyr.bounds.right * sx))))
        y2 = max(y1 + 1, min(base.height - 1, int(round(lyr.bounds.bottom * sy))))

        draw.rectangle([x1, y1, x2, y2], outline=color, width=2)
        label = f"#{lyr.index} {lyr.name[:24]}"
        bbox = draw.textbbox((0, 0), label, font=font)
        tw = bbox[2] - bbox[0] + 8
        th = bbox[3] - bbox[1] + 4
        ly = y1 - th if y1 >= th else y1
        draw.rectangle([x1, ly, min(base.width, x1 + tw), min(base.height, ly + th)], fill=(15, 23, 42, 210))
        draw.text((x1 + 4, ly + 2), label, fill=color, font=font)

    merged = Image.alpha_composite(base, overlay).convert("RGB")
    buf = io.BytesIO()
    merged.save(buf, format="JPEG", quality=88, optimize=True)
    return buf.getvalue(), merged.width, merged.height


def compose_contact_sheet(
    frames: Sequence[tuple[float, Image.Image]],
    comp_name: str,
    frame_rate: float = 30.0,
    columns: int = 3,
    cell_max_dimension: int = 480,
) -> tuple[bytes, int, int]:
    """Stitch multiple (time_seconds, frame_image) pairs into a labeled storyboard grid."""
    if not frames:
        raise ValueError("frames must contain at least one rendered frame.")

    cols = max(1, min(6, int(columns)))
    rows = math.ceil(len(frames) / cols)

    first_img = frames[0][1].convert("RGB")
    longest = max(first_img.width, first_img.height, 1)
    scale = min(1.0, cell_max_dimension / float(longest)) if cell_max_dimension > 0 else 1.0
    cell_w = max(64, int(round(first_img.width * scale)))
    cell_h = max(64, int(round(first_img.height * scale)))

    pad = 12
    header_h = 34
    label_h = 22
    sheet_w = pad + cols * (cell_w + pad)
    sheet_h = header_h + pad + rows * (cell_h + label_h + pad)

    sheet = Image.new("RGB", (sheet_w, sheet_h), color=(22, 24, 29))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()

    header_text = f"Contact Sheet: {comp_name} ({len(frames)} samples @ {frame_rate:g} fps)"
    draw.text((pad, 10), header_text, fill=(226, 232, 240), font=font)

    for idx, (t_sec, img) in enumerate(frames):
        r = idx // cols
        c = idx % cols
        x = pad + c * (cell_w + pad)
        y = header_h + pad + r * (cell_h + label_h + pad)

        thumb = img.convert("RGB").resize((cell_w, cell_h), Image.Resampling.LANCZOS)
        sheet.paste(thumb, (x, y))
        draw.rectangle([x, y, x + cell_w - 1, y + cell_h - 1], outline=(71, 85, 105), width=1)

        frame_num = int(round(t_sec * frame_rate))
        caption = f"#{idx + 1}  t={t_sec:.2f}s  (f={frame_num})"
        draw.text((x + 4, y + cell_h + 4), caption, fill=(148, 163, 184), font=font)

    buf = io.BytesIO()
    sheet.save(buf, format="JPEG", quality=86, optimize=True)
    return buf.getvalue(), sheet.width, sheet.height
