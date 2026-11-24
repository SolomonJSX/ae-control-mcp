"""FastMCP server exposing GUI automation and Adobe After Effects 2020 tools."""

from __future__ import annotations

import json
from typing import Literal

from mcp.server.fastmcp import FastMCP, Image

from . import after_effects, gui, visuals
from .ae_geometry import AfterEffectsGeometryProvider, parse_composition_geometry
from .geometry import LayoutPreset, analyze_motion_sequence, build_analyzer_for_preset

mcp = FastMCP("ae-control-mcp")
_ae_geometry_provider = AfterEffectsGeometryProvider(after_effects.AfterEffectsScriptRunner())


@mcp.tool()
def take_screenshot(
    monitor_index: int = 1,
    window_title: str | None = None,
    image_format: Literal["png", "jpeg"] = "jpeg",
    max_dimension: int | None = None,
) -> list[object]:
    """Capture a screenshot of the screen or a specific window.

    Returns the image and its coordinate metadata (width, height, original_width,
    original_height, offset_x, offset_y, scale_x, scale_y).
    To convert local image coordinates (ix, iy) to absolute screen coordinates:
      screen_x = round(ix * scale_x) + offset_x
      screen_y = round(iy * scale_y) + offset_y
    """
    shot = gui.capture_screenshot(
        monitor_index=monitor_index,
        window_title=window_title,
        image_format=image_format,
        max_dimension=max_dimension,
    )
    meta = json.dumps(
        {
            "width": shot.width,
            "height": shot.height,
            "original_width": shot.original_width,
            "original_height": shot.original_height,
            "offset_x": shot.offset_x,
            "offset_y": shot.offset_y,
            "scale_x": shot.scale_x,
            "scale_y": shot.scale_y,
        }
    )
    return [Image(data=shot.image_bytes, format=image_format), meta]


@mcp.tool()
def get_screen_info() -> dict[str, int]:
    """Return primary screen width and height in physical pixels."""
    width, height = gui.get_screen_size()
    return {"width": width, "height": height}


@mcp.tool()
def list_windows() -> list[dict[str, int | str | bool]]:
    """List open desktop windows with their titles and bounding rectangles."""
    return gui.list_open_windows()


@mcp.tool()
def focus_window(title_query: str) -> dict[str, int | str]:
    """Restore and bring the first window matching title_query to the foreground."""
    return gui.focus_window(title_query)


@mcp.tool()
def mouse_move(
    x: int,
    y: int,
    duration: float = 0.15,
    target_window: str | None = None,
) -> dict[str, int]:
    """Move the mouse cursor to absolute screen coordinates (x, y).

    If target_window is provided, refuses to move outside that window's bounds.
    """
    nx, ny = gui.move_mouse(x=x, y=y, duration=duration, target_window=target_window)
    return {"x": nx, "y": ny}


@mcp.tool()
def mouse_click(
    x: int | None = None,
    y: int | None = None,
    button: Literal["left", "right", "middle"] = "left",
    clicks: int = 1,
    target_window: str | None = None,
) -> dict[str, int]:
    """Click the mouse at (x, y) or at the current cursor position.

    If target_window is provided, refuses to click outside that window's bounds.
    """
    nx, ny = gui.click_mouse(
        x=x,
        y=y,
        button=button,
        clicks=clicks,
        target_window=target_window,
    )
    return {"x": nx, "y": ny}


@mcp.tool()
def mouse_drag(
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
    duration: float = 0.3,
    button: Literal["left", "right", "middle"] = "left",
    target_window: str | None = None,
) -> dict[str, int]:
    """Drag the mouse from (start_x, start_y) to (end_x, end_y).

    If target_window is provided, refuses to drag outside that window's bounds.
    """
    nx, ny = gui.drag_mouse(
        start_x=start_x,
        start_y=start_y,
        end_x=end_x,
        end_y=end_y,
        duration=duration,
        button=button,
        target_window=target_window,
    )
    return {"x": nx, "y": ny}


@mcp.tool()
def mouse_scroll(
    clicks: int,
    x: int | None = None,
    y: int | None = None,
    target_window: str | None = None,
) -> dict[str, int | bool]:
    """Scroll vertically (positive = up, negative = down), optionally guarded by target_window."""
    gui.scroll_mouse(clicks=clicks, x=x, y=y, target_window=target_window)
    return {"ok": True, "clicks": clicks}


@mcp.tool()
def keyboard_type(text: str, interval: float = 0.01) -> dict[str, bool]:
    """Type text at the current keyboard focus (supports ASCII and Unicode/Cyrillic)."""
    gui.type_text(text=text, interval=interval)
    return {"ok": True}


@mcp.tool()
def keyboard_hotkey(
    keys: list[str],
    target_window: str | None = None,
) -> dict[str, object]:
    """Press a key or hotkey combination (e.g. ['space'] or ['ctrl', 'z']).

    Blocks project-saving/closing shortcuts (Ctrl+S, Ctrl+W, Ctrl+Q, Alt+F4) in After Effects.
    """
    gui.press_hotkey(keys=keys, target_window=target_window)
    return {"ok": True, "keys": keys}


@mcp.tool()
def ae_get_project_info(timeout_seconds: float = 15.0) -> dict[str, object]:
    """Read-only: inspect the currently open After Effects 2020 project, compositions, and layers."""
    return after_effects.get_project_info(timeout_seconds=timeout_seconds)


@mcp.tool()
def ae_inspect_composition(
    comp_name: str | None = None,
    layer_index: int | None = None,
    layer_name: str | None = None,
    time_seconds: float | None = None,
    timeout_seconds: float = 15.0,
) -> dict[str, object]:
    """Read-only deep inspection of composition markers, layer transforms, text styles, effects, and keyframes."""
    return after_effects.inspect_composition(
        comp_name=comp_name,
        layer_index=layer_index,
        layer_name=layer_name,
        time_seconds=time_seconds,
        timeout_seconds=timeout_seconds,
    )


@mcp.tool()
def ae_audit_project(timeout_seconds: float = 20.0) -> dict[str, object]:
    """Read-only health audit: detect missing footage, broken expressions, fonts used, unused items, and render templates."""
    return after_effects.audit_project(timeout_seconds=timeout_seconds)


@mcp.tool()
def ae_write_script(
    output_path: str,
    script_code: str,
    undo_group_name: str | None = None,
    overwrite: bool = True,
    include_stdlib: bool = False,
    strict: bool = False,
) -> dict[str, object]:
    """Write an ES3 ExtendScript (.jsx) file to disk for the user to run manually in After Effects.

    - Writes UTF-8 with BOM (for Cyrillic support in AE 2020) and runs the lexical ES3 + safety linter.
    - Pass undo_group_name to automatically wrap the script in app.beginUndoGroup/try/catch/finally.
    - Pass include_stdlib=True to inject AEH helpers (AEH.findComp, AEH.hexToRgb, AEH.centerAnchor, AEH.easyEase, AEH.addText).
    - Pass strict=True to block writing if any ES6+/save() lint errors are detected.
    """
    return after_effects.write_extendscript_file(
        output_path=output_path,
        script_code=script_code,
        undo_group_name=undo_group_name,
        overwrite=overwrite,
        include_stdlib=include_stdlib,
        strict=strict,
    )


@mcp.tool()
def ae_cleanup_artifacts(
    target_dir: str | None = None,
    extra_paths: list[str] | None = None,
    clean_temp: bool = True,
    recursive: bool = False,
    dry_run: bool = False,
) -> dict[str, object]:
    """Clean up old screenshots, preview frames, and temporary junk files while keeping all .jsx scripts."""
    return after_effects.cleanup_artifacts(
        target_dir=target_dir,
        extra_paths=extra_paths,
        clean_temp=clean_temp,
        recursive=recursive,
        dry_run=dry_run,
    )


@mcp.tool()
def ae_render_frame_preview(
    comp_name: str | None = None,
    time_seconds: float | None = None,
    max_dimension: int = 1280,
    timeout_seconds: float = 30.0,
) -> list[object]:
    """Render an exact composition frame directly from After Effects for visual inspection."""
    preview = after_effects.save_frame_preview(
        comp_name=comp_name,
        time_seconds=time_seconds,
        max_dimension=max_dimension,
        timeout_seconds=timeout_seconds,
    )
    meta = json.dumps(
        {
            "comp_name": preview.comp_name,
            "time_seconds": preview.time_seconds,
            "frame_rate": preview.frame_rate,
            "width": preview.width,
            "height": preview.height,
        }
    )
    return [Image(data=preview.image_bytes, format="jpeg"), meta]


@mcp.tool()
def ae_render_annotated_preview(
    comp_name: str | None = None,
    time_seconds: float | None = None,
    preset: LayoutPreset = "standard",
    check_contrast: bool = True,
    max_dimension: int = 1280,
    timeout_seconds: float = 30.0,
) -> list[object]:
    """Render a composition frame and overlay safe-zone guides, layer bounding boxes, and layout/contrast warnings."""
    rgb, _meta = after_effects.render_raw_frame(
        comp_name=comp_name,
        time_seconds=time_seconds,
        timeout_seconds=timeout_seconds,
    )
    comp = _ae_geometry_provider.get_composition_geometry(
        comp_name=comp_name,
        time_seconds=time_seconds,
    )
    analyzer = build_analyzer_for_preset(
        preset=preset,
        frame_image=rgb if check_contrast else None,
        is_vertical_comp=comp.is_vertical,
    )
    report = analyzer.analyze(comp)
    include_social = preset == "social_vertical" or (preset == "full" and comp.is_vertical)
    img_bytes, out_w, out_h = visuals.annotate_layout_frame(
        frame_image=rgb,
        comp=comp,
        report=report,
        include_social_zones=include_social,
        max_dimension=max_dimension,
    )
    payload = report.to_dict()
    payload["annotated_width"] = out_w
    payload["annotated_height"] = out_h
    return [Image(data=img_bytes, format="jpeg"), json.dumps(payload)]


@mcp.tool()
def ae_render_contact_sheet(
    comp_name: str | None = None,
    timestamps: list[float] | None = None,
    num_frames: int = 6,
    columns: int = 3,
    cell_max_dimension: int = 480,
    timeout_seconds: float = 45.0,
) -> list[object]:
    """Render multiple frames across a composition's work area into a labeled storyboard grid."""
    frames, meta = after_effects.render_multiple_frames(
        comp_name=comp_name,
        timestamps=timestamps,
        num_frames=num_frames,
        timeout_seconds=timeout_seconds,
    )
    resolved_name = str(meta.get("compName") or comp_name or "Composition")
    fps = float(meta.get("frameRate") or 30.0)
    sheet_bytes, width, height = visuals.compose_contact_sheet(
        frames=frames,
        comp_name=resolved_name,
        frame_rate=fps,
        columns=columns,
        cell_max_dimension=cell_max_dimension,
    )
    info = json.dumps(
        {
            "comp_name": resolved_name,
            "frame_rate": fps,
            "sampled_times": [round(ts, 3) for ts, _ in frames],
            "sheet_width": width,
            "sheet_height": height,
        }
    )
    return [Image(data=sheet_bytes, format="jpeg"), info]


@mcp.tool()
def ae_render(
    project_path: str,
    comp_name: str,
    output_path: str,
    render_settings: str | None = None,
    output_module: str | None = None,
    start_frame: int | None = None,
    end_frame: int | None = None,
    sound: bool = True,
    timeout_seconds: float = 300.0,
) -> dict[str, object]:
    """Render a saved After Effects 2020 composition via aerender.exe."""
    return after_effects.render_composition(
        project_path=project_path,
        comp_name=comp_name,
        output_path=output_path,
        render_settings=render_settings,
        output_module=output_module,
        start_frame=start_frame,
        end_frame=end_frame,
        sound=sound,
        timeout_seconds=timeout_seconds,
    )


@mcp.tool()
def ae_analyze_layout(
    comp_name: str | None = None,
    time_seconds: float | None = None,
    preset: LayoutPreset = "standard",
) -> dict[str, object]:
    """Extract parent-aware composition & layer geometry from AE 2020 and evaluate spatial layout rules.

    Presets:
    - 'standard': bounds_check + safe_zone (10% title-safe) + overlap_check
    - 'social_vertical': standard + social_safe_zone (9:16 Reels/TikTok/Shorts UI dead-zones)
    - 'full': all rules including alignment_consistency (and social_safe_zone on vertical comps)
    """
    comp = _ae_geometry_provider.get_composition_geometry(
        comp_name=comp_name,
        time_seconds=time_seconds,
    )
    analyzer = build_analyzer_for_preset(preset=preset, is_vertical_comp=comp.is_vertical)
    return analyzer.analyze(comp).to_dict()


@mcp.tool()
def ae_analyze_motion(
    comp_name: str | None = None,
    timestamps: list[float] | None = None,
    sample_count: int = 6,
    preset: LayoutPreset = "standard",
    timeout_seconds: float = 20.0,
) -> dict[str, object]:
    """Sample composition geometry across multiple timestamps in one AE call and detect layout issues over time."""
    samples = _ae_geometry_provider.get_motion_geometry(
        comp_name=comp_name,
        timestamps=timestamps,
        sample_count=sample_count,
        timeout_seconds=timeout_seconds,
    )
    return analyze_motion_sequence(samples=samples, preset=preset).to_dict()


@mcp.tool()
def analyze_geometry_layout(
    comp_name: str,
    width: int,
    height: int,
    layers: list[dict[str, object]],
    time_seconds: float = 0.0,
    preset: LayoutPreset = "standard",
) -> dict[str, object]:
    """Analyze 2D composition/layer geometry offline without After Effects."""
    comp = parse_composition_geometry(
        {
            "name": comp_name,
            "width": width,
            "height": height,
            "timeSeconds": time_seconds,
            "layers": layers,
        }
    )
    analyzer = build_analyzer_for_preset(preset=preset, is_vertical_comp=comp.is_vertical)
    return analyzer.analyze(comp).to_dict()


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
