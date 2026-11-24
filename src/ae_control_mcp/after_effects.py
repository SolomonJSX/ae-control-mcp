"""Adobe After Effects 2020 read-only inspection, ES3 script writing, cleanup, and aerender."""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from .es3_linter import AE_ES3_STDLIB, lint_es3_script_detailed

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
                time.sleep(0.1)
                continue
        if proc is not None and exit_code is None:
            rc = proc.poll()
            if rc is not None:
                exit_code = rc
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
    """Execute read-only ExtendScript inside After Effects 2020 and return its JSON result."""
    afterfx = find_ae_executable("AfterFX.exe")

    with tempfile.TemporaryDirectory(prefix="ae_mcp_", ignore_cleanup_errors=True) as tmp_dir:
        tmp_path = Path(tmp_dir)
        jsx_path = tmp_path / "run.jsx"
        result_path = tmp_path / "result.json"
        done_path = tmp_path / "result.done"

        wrapped = _wrap_extendscript(script_code, result_path, done_path)
        jsx_path.write_text(wrapped, encoding="utf-8-sig")

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
                    if (lyr.source instanceof CompItem) return "precomp";
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


def inspect_composition(
    comp_name: str | None = None,
    layer_index: int | None = None,
    layer_name: str | None = None,
    time_seconds: float | None = None,
    timeout_seconds: float = 15.0,
) -> dict[str, Any]:
    """Read-only deep inspection of a composition's markers, layers, text styles, effects, and keyframes."""
    idx_filter = "null" if layer_index is None else str(int(layer_index))
    name_filter = _js_string(layer_name) if layer_name else "null"
    target_time = "null" if time_seconds is None else str(float(time_seconds))

    script = f"""
        {_comp_lookup_es3(comp_name)}
        var t = ({target_time} !== null) ? {target_time} : comp.time;
        var filterIdx = {idx_filter};
        var filterName = {name_filter};

        function __propSnapshot(prop, sampleT) {{
            if (!prop) return null;
            var val = null;
            try {{
                val = prop.valueAtTime(sampleT, false);
            }} catch (e) {{}}
            var info = {{
                value: val,
                numKeys: prop.numKeys || 0
            }};
            if (prop.numKeys && prop.numKeys > 0) {{
                info.firstKeyTime = prop.keyTime(1);
                info.lastKeyTime = prop.keyTime(prop.numKeys);
            }}
            try {{
                if (prop.canSetExpression && prop.expressionEnabled) {{
                    info.expression = prop.expression;
                    info.expressionError = prop.expressionError || "";
                }}
            }} catch (ee) {{}}
            return info;
        }}

        function __readMarkers(markerProp) {{
            var out = [];
            if (!markerProp || !markerProp.numKeys) return out;
            for (var m = 1; m <= markerProp.numKeys; m++) {{
                try {{
                    var mv = markerProp.keyValue(m);
                    out.push({{
                        time: markerProp.keyTime(m),
                        comment: mv.comment || "",
                        duration: mv.duration || 0,
                        chapter: mv.chapter || ""
                    }});
                }} catch (me) {{}}
            }}
            return out;
        }}

        var compMarkers = [];
        try {{
            compMarkers = __readMarkers(comp.markerProperty);
        }} catch (ce) {{}}

        var layers = [];
        for (var i = 1; i <= comp.numLayers; i++) {{
            var lyr = comp.layer(i);
            if (filterIdx !== null && lyr.index !== filterIdx) continue;
            if (filterName !== null && lyr.name !== filterName) continue;

            var ltype = "other";
            if (lyr instanceof TextLayer) ltype = "text";
            else if (lyr instanceof ShapeLayer) ltype = "shape";
            else if (lyr instanceof CameraLayer) ltype = "camera";
            else if (lyr instanceof LightLayer) ltype = "light";
            else if (lyr.nullLayer) ltype = "null";
            else if (lyr instanceof AVLayer) {{
                try {{
                    if (lyr.source instanceof CompItem) ltype = "precomp";
                    else if (lyr.source && lyr.source.mainSource instanceof SolidSource) ltype = "solid";
                    else ltype = "av";
                }} catch (se) {{ ltype = "av"; }}
            }}

            var tr = lyr.transform;
            var transformInfo = null;
            if (tr) {{
                transformInfo = {{
                    anchorPoint: __propSnapshot(tr.anchorPoint, t),
                    position: tr.position && tr.position.dimensionsSeparated
                        ? {{
                            separated: true,
                            x: __propSnapshot(tr.property("ADBE Position_0"), t),
                            y: __propSnapshot(tr.property("ADBE Position_1"), t)
                        }}
                        : __propSnapshot(tr.position, t),
                    scale: __propSnapshot(tr.scale, t),
                    rotation: __propSnapshot(tr.rotation || tr.zRotation, t),
                    opacity: __propSnapshot(tr.opacity, t)
                }};
            }}

            var textInfo = null;
            if (lyr instanceof TextLayer) {{
                try {{
                    var srcText = lyr.property("Source Text");
                    var td = srcText.valueAtTime(t, false);
                    textInfo = {{
                        text: td.text,
                        font: td.font,
                        fontSize: td.fontSize,
                        applyFill: !!td.applyFill,
                        fillColor: td.applyFill ? [td.fillColor[0], td.fillColor[1], td.fillColor[2]] : null,
                        applyStroke: !!td.applyStroke,
                        strokeColor: td.applyStroke ? [td.strokeColor[0], td.strokeColor[1], td.strokeColor[2]] : null,
                        strokeWidth: td.applyStroke ? td.strokeWidth : 0,
                        tracking: td.tracking,
                        justification: String(td.justification),
                        numKeys: srcText.numKeys || 0
                    }};
                }} catch (te) {{}}
            }}

            var effects = [];
            try {{
                var fxGroup = lyr.property("ADBE Effect Parade");
                if (fxGroup) {{
                    for (var f = 1; f <= fxGroup.numProperties; f++) {{
                        var fx = fxGroup.property(f);
                        effects.push({{
                            index: f,
                            name: fx.name,
                            matchName: fx.matchName,
                            enabled: !!fx.enabled
                        }});
                    }}
                }}
            }} catch (fe) {{}}

            var sourceInfo = null;
            try {{
                if (lyr instanceof AVLayer && lyr.source) {{
                    sourceInfo = {{
                        id: lyr.source.id,
                        name: lyr.source.name,
                        isPrecomp: (lyr.source instanceof CompItem),
                        footageMissing: (lyr.source instanceof FootageItem) ? !!lyr.source.footageMissing : false
                    }};
                }}
            }} catch (srcErr) {{}}

            layers.push({{
                index: lyr.index,
                name: lyr.name,
                type: ltype,
                enabled: !!lyr.enabled,
                solo: !!lyr.solo,
                locked: !!lyr.locked,
                threeDLayer: !!lyr.threeDLayer,
                parentIndex: lyr.parent ? lyr.parent.index : null,
                parentName: lyr.parent ? lyr.parent.name : null,
                inPoint: lyr.inPoint,
                outPoint: lyr.outPoint,
                startTime: lyr.startTime,
                stretch: lyr.stretch,
                transform: transformInfo,
                text: textInfo,
                effects: effects,
                markers: __readMarkers(lyr.property("ADBE Marker")),
                source: sourceInfo
            }});
        }}

        return {{
            compName: comp.name,
            width: comp.width,
            height: comp.height,
            pixelAspect: comp.pixelAspect,
            frameRate: comp.frameRate,
            duration: comp.duration,
            timeSeconds: t,
            workAreaStart: comp.workAreaStart,
            workAreaDuration: comp.workAreaDuration,
            markers: compMarkers,
            layers: layers
        }};
    """
    return run_extendscript(script, timeout_seconds=timeout_seconds)


def audit_project(timeout_seconds: float = 20.0) -> dict[str, Any]:
    """Read-only health audit: missing footage, broken expressions, fonts used, unused items, and render templates."""
    script = """
        var proj = app.project;
        if (!proj) return { hasProject: false };

        var missingFootage = [];
        var unusedFootage = [];
        var expressionErrors = [];
        var fontsMap = {};
        var fontsUsed = [];
        var compCount = 0;

        function __scanProps(group, compName, lyrIndex, lyrName, depth) {
            if (!group || depth > 4 || !group.numProperties) return;
            for (var p = 1; p <= group.numProperties; p++) {
                var pr = group.property(p);
                if (!pr) continue;
                try {
                    if (pr.canSetExpression && pr.expressionEnabled && pr.expressionError && pr.expressionError !== "") {
                        expressionErrors.push({
                            compName: compName,
                            layerIndex: lyrIndex,
                            layerName: lyrName,
                            propertyName: pr.name,
                            matchName: pr.matchName,
                            error: pr.expressionError
                        });
                    }
                } catch (e) {}
                if (pr.numProperties && pr.numProperties > 0) {
                    __scanProps(pr, compName, lyrIndex, lyrName, depth + 1);
                }
            }
        }

        for (var i = 1; i <= proj.numItems; i++) {
            var item = proj.item(i);
            if (item instanceof FootageItem) {
                var fPath = null;
                try {
                    if (item.file) fPath = item.file.fsName;
                } catch (fe) {}
                if (item.footageMissing) {
                    missingFootage.push({
                        id: item.id,
                        name: item.name,
                        missingPath: item.missingFootagePath || fPath
                    });
                }
                var isSolid = false;
                try {
                    isSolid = (item.mainSource instanceof SolidSource);
                } catch (se) {}
                if (!isSolid && item.usedIn && item.usedIn.length === 0) {
                    unusedFootage.push({ id: item.id, name: item.name, file: fPath });
                }
            } else if (item instanceof CompItem) {
                compCount++;
                for (var l = 1; l <= item.numLayers; l++) {
                    var lyr = item.layer(l);
                    if (lyr instanceof TextLayer) {
                        try {
                            var td = lyr.property("Source Text").value;
                            if (td && td.font && !fontsMap[td.font]) {
                                fontsMap[td.font] = true;
                                fontsUsed.push(td.font);
                            }
                        } catch (te) {}
                    }
                    __scanProps(lyr, item.name, lyr.index, lyr.name, 1);
                }
            }
        }

        var renderTemplates = { renderSettings: [], outputModules: [] };
        try {
            if (proj.renderQueue && proj.renderQueue.numItems > 0) {
                var rqItem = proj.renderQueue.item(1);
                if (rqItem.templates) renderTemplates.renderSettings = rqItem.templates;
                if (rqItem.numOutputModules > 0 && rqItem.outputModule(1).templates) {
                    renderTemplates.outputModules = rqItem.outputModule(1).templates;
                }
            }
        } catch (rqe) {}

        return {
            hasProject: true,
            file: proj.file ? proj.file.fsName : null,
            totalItems: proj.numItems,
            compCount: compCount,
            missingFootageCount: missingFootage.length,
            expressionErrorCount: expressionErrors.length,
            unusedFootageCount: unusedFootage.length,
            missingFootage: missingFootage,
            expressionErrors: expressionErrors,
            unusedFootage: unusedFootage,
            fontsUsed: fontsUsed,
            renderTemplates: renderTemplates
        };
    """
    return run_extendscript(script, timeout_seconds=timeout_seconds)


def _wait_for_png_image(png_path: Path, deadline: float) -> Image.Image:
    """Poll until After Effects finishes writing png_path asynchronously and return an RGB PIL Image."""
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        if png_path.is_file() and png_path.stat().st_size > 0:
            try:
                with Image.open(png_path) as img:
                    img.load()
                    return img.convert("RGB")
            except (PermissionError, OSError) as exc:
                last_err = exc
        time.sleep(0.15)

    detail = f" ({last_err})" if last_err else ""
    raise RuntimeError(f"After Effects did not finish writing preview PNG '{png_path.name}'{detail}.")


def render_raw_frame(
    comp_name: str | None = None,
    time_seconds: float | None = None,
    timeout_seconds: float = 30.0,
) -> tuple[Image.Image, dict[str, Any]]:
    """Render a single full-resolution RGB PIL Image and metadata dict via comp.saveFrameToPng."""
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

        deadline = time.monotonic() + timeout_seconds
        rgb = _wait_for_png_image(png_path, deadline)
        meta = resp.get("result") or {}
        return rgb, meta


def save_frame_preview(
    comp_name: str | None = None,
    time_seconds: float | None = None,
    max_dimension: int = 1280,
    timeout_seconds: float = 30.0,
) -> FramePreviewResult:
    """Render an exact frame of an AE composition to JPEG bytes via comp.saveFrameToPng."""
    rgb, meta = render_raw_frame(
        comp_name=comp_name,
        time_seconds=time_seconds,
        timeout_seconds=timeout_seconds,
    )
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


def render_multiple_frames(
    comp_name: str | None = None,
    timestamps: list[float] | None = None,
    num_frames: int = 6,
    timeout_seconds: float = 45.0,
) -> tuple[list[tuple[float, Image.Image]], dict[str, Any]]:
    """Render multiple frames in a single ExtendScript round-trip for storyboard / contact sheets."""
    count = max(2, min(16, int(num_frames)))
    explicit_js = (
        "[" + ", ".join(str(float(ts)) for ts in timestamps) + "]"
        if timestamps
        else "null"
    )

    with tempfile.TemporaryDirectory(prefix="ae_frame_", ignore_cleanup_errors=True) as tmp_dir:
        tmp_path = Path(tmp_dir)
        out_dir_js = _js_string(str(tmp_path))
        script = f"""
            {_comp_lookup_es3(comp_name)}
            var outDir = {out_dir_js};
            var explicitTimes = {explicit_js};
            var times = [];
            var maxT = Math.max(0, comp.duration - comp.frameDuration);
            if (explicitTimes !== null && explicitTimes.length > 0) {{
                for (var e = 0; e < explicitTimes.length; e++) {{
                    times.push(Math.min(maxT, Math.max(0, explicitTimes[e])));
                }}
            }} else {{
                var startT = comp.workAreaStart;
                var durT = comp.workAreaDuration;
                var n = {count};
                for (var s = 0; s < n; s++) {{
                    var ratio = (n === 1) ? 0.0 : (s / (n - 1));
                    times.push(Math.min(maxT, Math.max(0, startT + durT * ratio)));
                }}
            }}
            var files = [];
            for (var i = 0; i < times.length; i++) {{
                var fname = "frame_" + i + ".png";
                var f = new File(outDir + "/" + fname);
                comp.saveFrameToPng(times[i], f);
                files.push({{ index: i, timeSeconds: times[i], fileName: fname }});
            }}
            return {{
                compName: comp.name,
                frameRate: comp.frameRate,
                width: comp.width,
                height: comp.height,
                frames: files
            }};
        """
        resp = run_extendscript(script, timeout_seconds=timeout_seconds)
        if not resp.get("ok"):
            raise RuntimeError(resp.get("error") or "Failed to render storyboard frames.")

        meta = resp.get("result") or {}
        frame_specs = meta.get("frames") or []
        deadline = time.monotonic() + timeout_seconds
        rendered: list[tuple[float, Image.Image]] = []
        for spec in frame_specs:
            png_path = tmp_path / str(spec["fileName"])
            img = _wait_for_png_image(png_path, deadline)
            rendered.append((float(spec["timeSeconds"]), img))

        return rendered, meta


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
    "contact_sheet",
    "annotated_",
    "debug_",
    "tmp_",
    "temp_",
    "capture_",
)
_JUNK_FILE_EXTENSIONS = frozenset({".tmp", ".bak", ".log", ".done"})
_JUNK_EXACT_NAMES = frozenset({"result.json", "result.done"})


def _lint_es3_script(script_code: str) -> list[str]:
    """Return formatted ES3 / safety warning strings with line numbers."""
    return [issue.format_warning() for issue in lint_es3_script_detailed(script_code)]


def write_extendscript_file(
    output_path: str,
    script_code: str,
    undo_group_name: str | None = None,
    overwrite: bool = True,
    include_stdlib: bool = False,
    strict: bool = False,
) -> dict[str, Any]:
    """Write an ES3 ExtendScript (.jsx) file in UTF-8 with BOM without running or saving AE."""
    target = Path(output_path).expanduser().resolve()
    if target.suffix.lower() != ".jsx":
        target = target.with_suffix(".jsx")

    if target.exists() and not overwrite:
        raise FileExistsError(f"Script file already exists and overwrite=False: {target}")

    body = script_code.strip()
    stdlib_block = (AE_ES3_STDLIB.strip() + "\n\n") if include_stdlib else ""

    if undo_group_name and "beginUndoGroup" not in body:
        escaped_group = _js_string(undo_group_name)
        combined = stdlib_block + body
        indented = "\n".join(f"        {line}" if line.strip() else "" for line in combined.splitlines())
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
        final_code = stdlib_block + body + "\n"

    issues = lint_es3_script_detailed(final_code)
    warnings = [item.format_warning() for item in issues]
    has_errors = any(item.severity == "error" for item in issues)

    if strict and has_errors:
        return {
            "ok": False,
            "written": False,
            "path": str(target),
            "bytes_written": 0,
            "wrapped_in_undo_group": bool(undo_group_name and "beginUndoGroup" not in body),
            "included_stdlib": include_stdlib,
            "warnings": warnings,
            "issues": [item.to_dict() for item in issues],
        }

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(final_code, encoding="utf-8-sig")

    return {
        "ok": True,
        "written": True,
        "path": str(target),
        "bytes_written": target.stat().st_size,
        "wrapped_in_undo_group": bool(undo_group_name and "beginUndoGroup" not in body),
        "included_stdlib": include_stdlib,
        "warnings": warnings,
        "issues": [item.to_dict() for item in issues],
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
        "freed_bytes": freed_bytes,
        "errors": errors,
    }
