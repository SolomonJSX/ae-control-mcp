"""FastMCP server exposing GUI automation and Adobe After Effects 2020 tools."""

from __future__ import annotations

import json
from typing import Literal

from mcp.server.fastmcp import FastMCP, Image

from . import after_effects, gui
from .ae_geometry import AfterEffectsGeometryProvider, parse_composition_geometry
from .geometry import CompositeLayoutAnalyzer

mcp = FastMCP("ae-control-mcp")
_ae_geometry_provider = AfterEffectsGeometryProvider(after_effects.AfterEffectsScriptRunner())
_layout_analyzer = CompositeLayoutAnalyzer()


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
) -> dict[str, int | bool]:
    """Scroll vertically (positive = up, negative = down)."""
    gui.scroll_mouse(clicks=clicks, x=x, y=y)
    return {"ok": True, "clicks": clicks}


@mcp.tool()
def keyboard_type(text: str, interval: float = 0.01) -> dict[str, bool]:
    """Type text at the current keyboard focus (supports ASCII and Unicode/Cyrillic)."""
    gui.type_text(text=text, interval=interval)
    return {"ok": True}


@mcp.tool()
def keyboard_hotkey(keys: list[str]) -> dict[str, object]:
    """Press a key or hotkey combination, e.g. ['ctrl', 's'] or ['space']."""
    gui.press_hotkey(keys=keys)
    return {"ok": True, "keys": keys}


@mcp.tool()
def ae_get_project_info(timeout_seconds: float = 15.0) -> dict[str, object]:
    """Read-only: inspect the currently open After Effects 2020 project, compositions, and layers."""
    return after_effects.get_project_info(timeout_seconds=timeout_seconds)


@mcp.tool()
def ae_write_script(
    output_path: str,
    script_code: str,
    undo_group_name: str | None = None,
    overwrite: bool = True,
) -> dict[str, object]:
    """Write an ES3 ExtendScript (.jsx) file to disk for the user to run manually in After Effects.

    Does NOT execute the script in After Effects and does NOT save or modify the .aep project.
    Writes UTF-8 with BOM (for Cyrillic support in AE 2020) and checks for ES6+ syntax warnings.
    Pass undo_group_name to automatically wrap the script in app.beginUndoGroup/try/catch/finally.
    """
    return after_effects.write_extendscript_file(
        output_path=output_path,
        script_code=script_code,
        undo_group_name=undo_group_name,
        overwrite=overwrite,
    )


@mcp.tool()
def ae_cleanup_artifacts(
    target_dir: str | None = None,
    extra_paths: list[str] | None = None,
    clean_temp: bool = True,
    recursive: bool = False,
    dry_run: bool = False,
) -> dict[str, object]:
    """Clean up old screenshots, preview frames, and temporary junk files while keeping all .jsx scripts.

    - clean_temp=True removes leftover ae_mcp_*/ae_frame_* folders from the system temp directory.
    - target_dir scans a folder for temporary screenshot/preview images and junk (.tmp/.bak/.log).
    - extra_paths deletes specific temporary files/folders passed explicitly.
    - Protected files (.jsx, .jsxbin, .aep, .aepx, .prproj, .psd, .ai, .ffx) are NEVER deleted.
    """
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
    """Render an exact composition frame directly from After Effects for visual inspection.

    Uses comp.saveFrameToPng without stealing window focus or capturing AE UI chrome.
    Returns [Image, metadata_json].
    """
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
) -> dict[str, object]:
    """Extract composition & layer geometry from After Effects 2020 and evaluate layout rules.

    Detects out-of-frame layers, clipped edges, text outside title-safe margins, and overlaps.
    """
    comp = _ae_geometry_provider.get_composition_geometry(
        comp_name=comp_name,
        time_seconds=time_seconds,
    )
    return _layout_analyzer.analyze(comp).to_dict()


@mcp.tool()
def analyze_geometry_layout(
    comp_name: str,
    width: int,
    height: int,
    layers: list[dict[str, object]],
    time_seconds: float = 0.0,
) -> dict[str, object]:
    """Analyze 2D composition/layer geometry and return spatial conclusions without AE.

    Each item in `layers` should contain: index, name, enabled (bool), isText (bool),
    and bounds: {left, top, width, height}.
    """
    comp = parse_composition_geometry(
        {
            "name": comp_name,
            "width": width,
            "height": height,
            "timeSeconds": time_seconds,
            "layers": layers,
        }
    )
    return _layout_analyzer.analyze(comp).to_dict()


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
