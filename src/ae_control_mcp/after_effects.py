"""Adobe After Effects 2020 automation via ExtendScript (.jsx) and aerender."""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

DEFAULT_AE_DIRS = [
    Path(r"C:\Program Files\Adobe\Adobe After Effects 2020\Support Files"),
]


@dataclass(frozen=True)
class FramePreviewResult:
    image_bytes: bytes
    mime_type: str
    width: int
    height: int
    comp_name: str
    time_seconds: float
    frame_rate: float


def _discover_support_dirs() -> list[Path]:
    """Return candidate After Effects Support Files directories."""
    dirs = list(DEFAULT_AE_DIRS)
    adobe_root = Path(r"C:\Program Files\Adobe")
    if adobe_root.is_dir():
        for entry in sorted(adobe_root.glob("Adobe After Effects *"), reverse=True):
            support = entry / "Support Files"
            if support.is_dir() and support not in dirs:
                dirs.append(support)
    return dirs


def find_ae_executable(exe_name: str = "AfterFX.exe") -> Path:
    """Locate AfterFX.exe or aerender.exe, respecting env overrides."""
    env_var = "AE_RENDER_PATH" if exe_name.lower() == "aerender.exe" else "AE_EXE_PATH"
    override = os.environ.get(env_var)
    if override:
        path = Path(override)
        if path.is_file():
            return path
        raise FileNotFoundError(f"{env_var} points to missing file: {override}")

    for support_dir in _discover_support_dirs():
        candidate = support_dir / exe_name
        if candidate.is_file():
            return candidate

    raise FileNotFoundError(
        f"Could not find {exe_name}. Set {env_var} or install Adobe After Effects 2020 "
        r"in C:\Program Files\Adobe\Adobe After Effects 2020\Support Files\."
    )


def _js_string(value: str) -> str:
    """Safely encode a Python string as an ES3 double-quoted string literal."""
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", "\\r")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def _wrap_extendscript(user_code: str, result_file: Path, done_file: Path) -> str:
    """Wrap user ExtendScript in an ES3-compatible try/catch + atomic JSON writer."""
    escaped_result = str(result_file).replace("\\", "\\\\")
    escaped_done = str(done_file).replace("\\", "\\\\")
    return f"""
(function () {{
    function __esc(str) {{
        var s = String(str);
        var out = "";
        for (var i = 0; i < s.length; i++) {{
            var ch = s.charAt(i);
            var code = s.charCodeAt(i);
            if (ch === "\\\\") out += "\\\\\\\\";
            else if (ch === '"') out += '\\\\"';
            else if (ch === "\\b") out += "\\\\b";
            else if (ch === "\\f") out += "\\\\f";
            else if (ch === "\\r") out += "\\\\r";
            else if (ch === "\\n") out += "\\\\n";
            else if (ch === "\\t") out += "\\\\t";
            else if (code < 0x20) {{
                var hex = code.toString(16);
                while (hex.length < 4) hex = "0" + hex;
                out += "\\\\u" + hex;
            }} else {{
                out += ch;
            }}
        }}
        return out;
    }}

    function __toJson(val, depth) {{
        if (depth === undefined) depth = 0;
        if (depth > 12) return '"[MaxDepth]"';
        if (val === null || val === undefined) return "null";
        var t = typeof val;
        if (t === "number") return isFinite(val) ? String(val) : "null";
        if (t === "boolean") return val ? "true" : "false";
        if (t === "string") return '"' + __esc(val) + '"';
        if (val instanceof Array) {{
            var items = [];
            for (var i = 0; i < val.length; i++) {{
                items.push(__toJson(val[i], depth + 1));
            }}
            return "[" + items.join(",") + "]";
        }}
        if (t === "object") {{
            var props = [];
            for (var k in val) {{
                try {{
                    if (val.hasOwnProperty(k) && typeof val[k] !== "function") {{
                        props.push('"' + __esc(k) + '":' + __toJson(val[k], depth + 1));
                    }}
                }} catch (propErr) {{}}
            }}
            return "{{" + props.join(",") + "}}";
        }}
        return '"' + __esc(String(val)) + '"';
    }}

    var __payload = {{ ok: true, result: null, error: null }};
    try {{
        var __fn = function () {{
{user_code}
        }};
        __payload.result = __fn();
    }} catch (err) {{
        __payload.ok = false;
        var __msg = err && err.toString ? err.toString() : String(err);
        if (err && err.line !== undefined) {{
            __msg += " (line " + err.line + ")";
        }}
        __payload.error = __msg;
    }}

    var __out = new File("{escaped_result}");
    __out.encoding = "UTF-8";
    if (__out.open("w")) {{
        __out.write(__toJson(__payload, 0));
        __out.close();
        var __done = new File("{escaped_done}");
        __done.encoding = "UTF-8";
        if (__done.open("w")) {{
            __done.write("1");
            __done.close();
        }}
    }}
}})();
"""


def _read_result_when_ready(
    result_path: Path,
    done_path: Path,
    timeout_seconds: float,
    proc: subprocess.Popen[bytes] | None = None,
) -> dict[str, Any]:
    """Poll until ExtendScript writes done_path, then parse result_path."""
    deadline = time.monotonic() + timeout_seconds
    exit_code: int | None = None
    while time.monotonic() < deadline:
        if done_path.is_file() and result_path.is_file():
            try:
                raw = result_path.read_text(encoding="utf-8-sig")
                return json.loads(raw)
            except (PermissionError, OSError, json.JSONDecodeError):
                # On Windows, AE or AV may briefly hold the file lock right after writing.
                time.sleep(0.1)
                continue
        if proc is not None and exit_code is None:
            rc = proc.poll()
            if rc is not None:
                exit_code = rc
                # On Windows, AfterFX.exe -r hands off to the running AE instance and
                # exits immediately with code 0 or 1 while AE is still running the script.
                if rc not in (0, 1):
                    return {
                        "ok": False,
                        "result": None,
                        "error": f"AfterFX.exe exited immediately with code {rc}.",
                    }
        time.sleep(0.1)

    extra_info = ""
    if proc is not None:
        extra_info = f" (pid={proc.pid}" + (f", exit_code={exit_code}" if exit_code is not None else "") + ")"
    return {
        "ok": False,
        "result": None,
        "error": (
            f"Timed out after {timeout_seconds}s waiting for After Effects to write "
            f"ExtendScript result{extra_info}. Check that: "
            "1) After Effects is open and no modal dialog is blocking execution; "
            "2) 'Edit -> Preferences -> Scripting & Expressions -> Allow Scripts to Write Files and Access Network' is enabled."
        ),
    }


def run_extendscript(script_code: str, timeout_seconds: float = 15.0) -> dict[str, Any]:
    """Execute ExtendScript inside After Effects 2020 and return its JSON result."""
    afterfx = find_ae_executable("AfterFX.exe")

    with tempfile.TemporaryDirectory(prefix="ae_mcp_", ignore_cleanup_errors=True) as tmp_dir:
        tmp_path = Path(tmp_dir)
        jsx_path = tmp_path / "run.jsx"
        result_path = tmp_path / "result.json"
        done_path = tmp_path / "result.done"

        wrapped = _wrap_extendscript(script_code, result_path, done_path)
        # UTF-8 with BOM ensures After Effects 2020 on Windows decodes Cyrillic/Unicode properly.
        jsx_path.write_text(wrapped, encoding="utf-8-sig")

        # AfterFX.exe -r sends the script to the running AE instance (or launches AE).
        proc = subprocess.Popen(
            [str(afterfx), "-r", str(jsx_path)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return _read_result_when_ready(
            result_path=result_path,
            done_path=done_path,
            timeout_seconds=timeout_seconds,
            proc=proc,
        )


def _comp_lookup_es3(comp_name: str | None) -> str:
    """Return ES3 snippet that resolves `comp` by name, activeItem, or first CompItem."""
    target = _js_string(comp_name) if comp_name else "null"
    return f"""
        var proj = app.project;
        if (!proj) throw new Error("No open After Effects project.");
        var targetName = {target};
        var comp = null;
        if (targetName !== null) {{
            for (var __ci = 1; __ci <= proj.numItems; __ci++) {{
                var __it = proj.item(__ci);
                if (__it instanceof CompItem && __it.name === targetName) {{
                    comp = __it;
                    break;
                }}
            }}
        }} else if (proj.activeItem instanceof CompItem) {{
            comp = proj.activeItem;
        }} else {{
            for (var __cj = 1; __cj <= proj.numItems; __cj++) {{
                if (proj.item(__cj) instanceof CompItem) {{
                    comp = proj.item(__cj);
                    break;
                }}
            }}
        }}
        if (!comp) throw new Error("Target composition not found.");
    """


def get_project_info(timeout_seconds: float = 15.0) -> dict[str, Any]:
    """Return active project path, active item, and composition/layer summary."""
    script = """
        function __layerType(lyr) {
            if (lyr instanceof TextLayer) return "text";
            if (lyr instanceof ShapeLayer) return "shape";
            if (lyr instanceof CameraLayer) return "camera";
            if (lyr instanceof LightLayer) return "light";
            if (lyr.nullLayer) return "null";
            if (lyr instanceof AVLayer) {
                try {
                    if (lyr.source && lyr.source.mainSource instanceof SolidSource) return "solid";
                } catch (e) {}
                return "av";
            }
            return "other";
        }

        var proj = app.project;
        if (!proj) {
            return { hasProject: false };
        }
        var comps = [];
        for (var i = 1; i <= proj.numItems; i++) {
            var item = proj.item(i);
            if (item instanceof CompItem) {
                var t = item.time;
                var layers = [];
                for (var j = 1; j <= item.numLayers; j++) {
                    var lyr = item.layer(j);
                    var activeAtTime = (!!lyr.enabled) && (t >= lyr.inPoint) && (t < lyr.outPoint);
                    layers.push({
                        index: lyr.index,
                        name: lyr.name,
                        type: __layerType(lyr),
                        enabled: !!lyr.enabled,
                        activeAtTime: activeAtTime,
                        hasVideo: !!lyr.hasVideo,
                        hasAudio: !!lyr.hasAudio,
                        parentIndex: lyr.parent ? lyr.parent.index : null,
                        inPoint: lyr.inPoint,
                        outPoint: lyr.outPoint
                    });
                }
                comps.push({
                    id: item.id,
                    name: item.name,
                    width: item.width,
                    height: item.height,
                    frameRate: item.frameRate,
                    duration: item.duration,
                    time: t,
                    workAreaStart: item.workAreaStart,
                    workAreaDuration: item.workAreaDuration,
                    numLayers: item.numLayers,
                    layers: layers
                });
            }
        }
        return {
            hasProject: true,
            file: proj.file ? proj.file.fsName : null,
            activeItem: proj.activeItem ? proj.activeItem.name : null,
            numItems: proj.numItems,
            compositions: comps
        };
    """
    return run_extendscript(script, timeout_seconds=timeout_seconds)


def create_composition(
    name: str,
    width: int = 1920,
    height: int = 1080,
    duration: float = 10.0,
    frame_rate: float = 30.0,
    bg_color: tuple[float, float, float] = (0.0, 0.0, 0.0),
    pixel_aspect: float = 1.0,
    timeout_seconds: float = 15.0,
) -> dict[str, Any]:
    """Create a new composition in After Effects and open it in the viewer."""
    r, g, b = (max(0.0, min(1.0, float(c))) for c in bg_color)
    script = f"""
        if (!app.project) app.newProject();
        app.beginUndoGroup("Create Composition");
        try {{
            var comp = app.project.items.addComp(
                {_js_string(name)},
                {int(width)},
                {int(height)},
                {float(pixel_aspect)},
                {float(duration)},
                {float(frame_rate)}
            );
            comp.bgColor = [{r}, {g}, {b}];
            comp.openInViewer();
            return {{
                id: comp.id,
                name: comp.name,
                width: comp.width,
                height: comp.height,
                duration: comp.duration,
                frameRate: comp.frameRate
            }};
        }} finally {{
            app.endUndoGroup();
        }}
    """
    return run_extendscript(script, timeout_seconds=timeout_seconds)


def import_media(
    file_path: str,
    comp_name: str | None = None,
    add_to_comp: bool = True,
    timeout_seconds: float = 20.0,
) -> dict[str, Any]:
    """Import an image, video, or audio file into the AE project (and optionally into a comp)."""
    resolved = Path(file_path).expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"Media file not found: {resolved}")

    add_block = ""
    if add_to_comp:
        add_block = f"""
            {_comp_lookup_es3(comp_name)}
            var addedLayer = comp.layers.add(footage);
            layerInfo = {{
                index: addedLayer.index,
                name: addedLayer.name,
                compName: comp.name
            }};
        """

    script = f"""
        if (!app.project) app.newProject();
        app.beginUndoGroup("Import Media");
        try {{
            var f = new File({_js_string(str(resolved))});
            if (!f.exists) throw new Error("File does not exist: " + f.fsName);
            var io = new ImportOptions(f);
            var footage = app.project.importFile(io);
            var layerInfo = null;
            {add_block}
            return {{
                itemId: footage.id,
                itemName: footage.name,
                width: footage.width || 0,
                height: footage.height || 0,
                duration: footage.duration || 0,
                addedLayer: layerInfo
            }};
        }} finally {{
            app.endUndoGroup();
        }}
    """
    return run_extendscript(script, timeout_seconds=timeout_seconds)


def save_project(
    file_path: str | None = None,
    timeout_seconds: float = 15.0,
) -> dict[str, Any]:
    """Save the active After Effects project to disk (required before aerender)."""
    if file_path:
        target = Path(file_path).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        save_stmt = f"""
            var outFile = new File({_js_string(str(target))});
            app.project.save(outFile);
        """
    else:
        save_stmt = """
            if (!app.project.file) {
                throw new Error("Project has never been saved. Provide file_path (e.g. C:\\\\path\\\\project.aep).");
            }
            app.project.save();
        """

    script = f"""
        if (!app.project) throw new Error("No open After Effects project.");
        {save_stmt}
        return {{
            saved: true,
            file: app.project.file ? app.project.file.fsName : null
        }};
    """
    return run_extendscript(script, timeout_seconds=timeout_seconds)


def save_frame_preview(
    comp_name: str | None = None,
    time_seconds: float | None = None,
    max_dimension: int = 1280,
    timeout_seconds: float = 30.0,
) -> FramePreviewResult:
    """Render an exact frame of an AE composition to PNG via comp.saveFrameToPng."""
    target_time = "null" if time_seconds is None else str(float(time_seconds))

    with tempfile.TemporaryDirectory(prefix="ae_frame_", ignore_cleanup_errors=True) as tmp_dir:
        png_path = Path(tmp_dir) / "frame.png"
        script = f"""
            {_comp_lookup_es3(comp_name)}
            var t = ({target_time} !== null) ? {target_time} : comp.time;
            if (t < 0) t = 0;
            var maxT = comp.duration - comp.frameDuration;
            if (maxT < 0) maxT = 0;
            if (t > maxT) t = maxT;
            var outFile = new File({_js_string(str(png_path))});
            comp.saveFrameToPng(t, outFile);
            return {{
                compName: comp.name,
                timeSeconds: t,
                frameRate: comp.frameRate,
                width: comp.width,
                height: comp.height,
                exists: outFile.exists
            }};
        """
        resp = run_extendscript(script, timeout_seconds=timeout_seconds)
        if not resp.get("ok"):
            raise RuntimeError(resp.get("error") or "Failed to render frame preview.")

        # comp.saveFrameToPng() is asynchronous in After Effects 2020: wait until
        # the PNG appears, is non-empty, and can be fully decoded by Pillow.
        deadline = time.monotonic() + timeout_seconds
        rgb: Image.Image | None = None
        last_err: Exception | None = None
        while time.monotonic() < deadline:
            if png_path.is_file() and png_path.stat().st_size > 0:
                try:
                    with Image.open(png_path) as img:
                        img.load()
                        rgb = img.convert("RGB")
                    break
                except (PermissionError, OSError) as exc:
                    last_err = exc
            time.sleep(0.15)

        if rgb is None:
            detail = f" ({last_err})" if last_err else ""
            raise RuntimeError(
                f"After Effects did not finish writing preview PNG within {timeout_seconds}s{detail}."
            )

        meta = resp.get("result") or {}
        if max_dimension > 0 and max(rgb.width, rgb.height) > max_dimension:
            ratio = max_dimension / float(max(rgb.width, rgb.height))
            new_size = (
                max(1, int(round(rgb.width * ratio))),
                max(1, int(round(rgb.height * ratio))),
            )
            rgb = rgb.resize(new_size, Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        rgb.save(buf, format="JPEG", quality=88, optimize=True)
        return FramePreviewResult(
            image_bytes=buf.getvalue(),
            mime_type="image/jpeg",
            width=rgb.width,
            height=rgb.height,
            comp_name=str(meta.get("compName", comp_name or "")),
            time_seconds=float(meta.get("timeSeconds", time_seconds or 0.0)),
            frame_rate=float(meta.get("frameRate", 30.0)),
        )


def render_composition(
    project_path: str,
    comp_name: str,
    output_path: str,
    render_settings: str | None = None,
    output_module: str | None = None,
    start_frame: int | None = None,
    end_frame: int | None = None,
    sound: bool = True,
    timeout_seconds: float = 300.0,
) -> dict[str, Any]:
    """Render a composition headlessly using aerender.exe."""
    aerender = find_ae_executable("aerender.exe")
    proj = Path(project_path).expanduser().resolve()
    if not proj.is_file():
        raise FileNotFoundError(f"Project file not found: {proj}")

    out = Path(output_path).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(aerender),
        "-project",
        str(proj),
        "-comp",
        comp_name,
        "-output",
        str(out),
        "-sound",
        "ON" if sound else "OFF",
    ]
    if render_settings:
        cmd.extend(["-RStemplate", render_settings])
    if output_module:
        cmd.extend(["-OMtemplate", output_module])
    if start_frame is not None:
        cmd.extend(["-s", str(int(start_frame))])
    if end_frame is not None:
        cmd.extend(["-e", str(int(end_frame))])

    completed = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    return {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": completed.stdout[-4000:],
        "stderr": completed.stderr[-4000:],
        "output_path": str(out),
    }


class AfterEffectsScriptRunner:
    """Default ScriptRunner backed by AfterFX.exe -r."""

    def run(self, script_code: str, timeout_seconds: float = 15.0) -> dict[str, Any]:
        return run_extendscript(script_code=script_code, timeout_seconds=timeout_seconds)


PROTECTED_EXTENSIONS = frozenset(
    {".jsx", ".jsxbin", ".aep", ".aepx", ".prproj", ".psd", ".ai", ".ffx"}
)
_TEMP_DIR_PREFIXES = ("ae_mcp_", "ae_frame_", "ae_dbg_", "ae_test_")
_JUNK_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp"})
_JUNK_IMAGE_MARKERS = (
    "screenshot",
    "screen_",
    "preview",
    "ae_frame",
    "ae_preview",
    "frame_preview",
    "debug_",
    "tmp_",
    "temp_",
    "capture_",
)
_JUNK_FILE_EXTENSIONS = frozenset({".tmp", ".bak", ".log", ".done"})
_JUNK_EXACT_NAMES = frozenset({"result.json", "result.done"})


def _lint_es3_script(script_code: str) -> list[str]:
    """Return non-fatal ES3 / safety warnings for an After Effects 2020 .jsx script."""
    warnings: list[str] = []
    if re.search(r"\b(?:let|const)\s+[A-Za-z_$]", script_code):
        warnings.append("Detected 'let'/'const' (ES6+); AE 2020 ExtendScript requires 'var'.")
    if "=>" in script_code:
        warnings.append("Detected arrow function '=>' (ES6+); AE 2020 requires 'function (...) {}'.")
    if "`" in script_code:
        warnings.append("Detected template literal backtick '`' (ES6+); use string concatenation '+'.")
    if "JSON.stringify" in script_code or "JSON.parse" in script_code:
        warnings.append("Detected 'JSON.stringify'/'JSON.parse', which do not exist in AE 2020 ES3.")
    if re.search(r"app\.project\.save\s*\(", script_code):
        warnings.append("Detected 'app.project.save()'; scripts should not auto-save the user's .aep project.")
    return warnings


def write_extendscript_file(
    output_path: str,
    script_code: str,
    undo_group_name: str | None = None,
    overwrite: bool = True,
) -> dict[str, Any]:
    """Write an ES3 ExtendScript (.jsx) file in UTF-8 with BOM without running or saving AE."""
    target = Path(output_path).expanduser().resolve()
    if target.suffix.lower() != ".jsx":
        target = target.with_suffix(".jsx")

    if target.exists() and not overwrite:
        raise FileExistsError(f"Script file already exists and overwrite=False: {target}")

    body = script_code.strip()
    if undo_group_name and "beginUndoGroup" not in body:
        escaped_group = _js_string(undo_group_name)
        indented = "\n".join(f"        {line}" if line.strip() else "" for line in body.splitlines())
        final_code = (
            "(function () {\n"
            f"    app.beginUndoGroup({escaped_group});\n"
            "    try {\n"
            f"{indented}\n"
            "    } catch (e) {\n"
            '        alert("ExtendScript error: " + e.toString() + " (line " + e.line + ")");\n'
            "    } finally {\n"
            "        app.endUndoGroup();\n"
            "    }\n"
            "})();\n"
        )
    else:
        final_code = body + "\n"

    warnings = _lint_es3_script(final_code)
    target.parent.mkdir(parents=True, exist_ok=True)
    # UTF-8 with BOM ensures After Effects 2020 on Windows decodes Cyrillic/Unicode properly.
    target.write_text(final_code, encoding="utf-8-sig")

    return {
        "ok": True,
        "path": str(target),
        "bytes_written": target.stat().st_size,
        "wrapped_in_undo_group": bool(undo_group_name and "beginUndoGroup" not in body),
        "warnings": warnings,
    }


def _path_size(path: Path) -> int:
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    if path.is_dir():
        for root, _dirs, files in os.walk(path):
            for name in files:
                try:
                    total += (Path(root) / name).stat().st_size
                except OSError:
                    pass
    return total


def _is_protected_file(path: Path) -> bool:
    return path.suffix.lower() in PROTECTED_EXTENSIONS


def _is_cleanup_candidate(path: Path) -> bool:
    if not path.is_file() or _is_protected_file(path):
        return False
    name_lower = path.name.lower()
    suffix_lower = path.suffix.lower()
    if name_lower in _JUNK_EXACT_NAMES or suffix_lower in _JUNK_FILE_EXTENSIONS:
        return True
    if suffix_lower in _JUNK_IMAGE_EXTENSIONS:
        return any(marker in name_lower for marker in _JUNK_IMAGE_MARKERS)
    return False


def cleanup_artifacts(
    target_dir: str | None = None,
    extra_paths: list[str] | None = None,
    clean_temp: bool = True,
    recursive: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Remove leftover screenshots, frame previews, and temp junk while preserving .jsx scripts."""
    deleted_files: list[str] = []
    deleted_dirs: list[str] = []
    skipped_protected: list[str] = []
    errors: list[str] = []
    freed_bytes = 0

    def _remove_file(p: Path) -> None:
        nonlocal freed_bytes
        if _is_protected_file(p):
            skipped_protected.append(str(p))
            return
        size = _path_size(p)
        if dry_run:
            deleted_files.append(str(p))
            freed_bytes += size
            return
        try:
            p.unlink()
            deleted_files.append(str(p))
            freed_bytes += size
        except OSError as exc:
            errors.append(f"{p}: {exc}")

    def _remove_dir(p: Path, allow_temp_dir: bool = False) -> None:
        nonlocal freed_bytes
        if not allow_temp_dir:
            # Never delete a user directory that contains protected scripts/projects.
            for child in p.rglob("*"):
                if child.is_file() and _is_protected_file(child):
                    skipped_protected.append(str(child))
                    return
        size = _path_size(p)
        if dry_run:
            deleted_dirs.append(str(p))
            freed_bytes += size
            return
        try:
            shutil.rmtree(p)
            deleted_dirs.append(str(p))
            freed_bytes += size
        except OSError as exc:
            errors.append(f"{p}: {exc}")

    if clean_temp:
        temp_root = Path(tempfile.gettempdir())
        if temp_root.is_dir():
            for entry in temp_root.iterdir():
                if entry.is_dir() and any(entry.name.startswith(pref) for pref in _TEMP_DIR_PREFIXES):
                    _remove_dir(entry, allow_temp_dir=True)

    if target_dir:
        root = Path(target_dir).expanduser().resolve()
        if not root.is_dir():
            errors.append(f"target_dir not found: {root}")
        else:
            iterator = root.rglob("*") if recursive else root.iterdir()
            for entry in list(iterator):
                if _is_cleanup_candidate(entry):
                    _remove_file(entry)

    if extra_paths:
        for raw_path in extra_paths:
            p = Path(raw_path).expanduser().resolve()
            if not p.exists():
                continue
            if p.is_file():
                _remove_file(p)
            elif p.is_dir():
                _remove_dir(p)

    return {
        "ok": len(errors) == 0,
        "dry_run": dry_run,
        "deleted_files": deleted_files,
        "deleted_dirs": deleted_dirs,
        "skipped_protected": skipped_protected,
        "errors": errors,
        "freed_bytes": freed_bytes,
    }
