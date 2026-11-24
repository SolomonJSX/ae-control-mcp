"""After Effects 2020 geometry provider using an injected ScriptRunner."""

from __future__ import annotations

from typing import Any

from .geometry.models import CompositionGeometry, LayerGeometry, Point2D, Rect
from .protocols import ScriptRunner

_ES3_GEOMETRY_HELPERS = """
        function __resolveComp(proj, targetName) {
            var comp = null;
            if (targetName !== null) {
                for (var i = 1; i <= proj.numItems; i++) {
                    var item = proj.item(i);
                    if (item instanceof CompItem && item.name === targetName) {
                        comp = item;
                        break;
                    }
                }
            } else if (proj.activeItem instanceof CompItem) {
                comp = proj.activeItem;
            } else {
                for (var j = 1; j <= proj.numItems; j++) {
                    if (proj.item(j) instanceof CompItem) {
                        comp = proj.item(j);
                        break;
                    }
                }
            }
            if (!comp) throw new Error("Target composition not found.");
            return comp;
        }

        function __getPos2D(tr, t) {
            if (!tr || !tr.position) return [0, 0];
            if (tr.position.dimensionsSeparated) {
                var px = tr.property("ADBE Position_0") ? tr.property("ADBE Position_0").valueAtTime(t, false) : 0;
                var py = tr.property("ADBE Position_1") ? tr.property("ADBE Position_1").valueAtTime(t, false) : 0;
                return [px, py];
            }
            var pv = tr.position.valueAtTime(t, false);
            return [pv[0], pv[1]];
        }

        function __getRotDeg(tr, t) {
            if (!tr) return 0;
            if (tr.rotation) return tr.rotation.valueAtTime(t, false);
            if (tr.zRotation) return tr.zRotation.valueAtTime(t, false);
            return 0;
        }

        function __applyNodeTransform(node, pt, t) {
            var tr = node.transform;
            if (!tr) return pt;
            var pos = __getPos2D(tr, t);
            var anc = tr.anchorPoint ? tr.anchorPoint.valueAtTime(t, false) : [0, 0];
            var scl = tr.scale ? tr.scale.valueAtTime(t, false) : [100, 100];
            var rot = __getRotDeg(tr, t);

            var dx = (pt[0] - anc[0]) * (scl[0] / 100.0);
            var dy = (pt[1] - anc[1]) * (scl[1] / 100.0);
            var rad = rot * Math.PI / 180.0;
            var cosR = Math.cos(rad);
            var sinR = Math.sin(rad);
            return [
                pos[0] + dx * cosR - dy * sinR,
                pos[1] + dx * sinR + dy * cosR
            ];
        }

        function __layerPointToComp(lyr, pt, t) {
            var cur = lyr;
            var p = [pt[0], pt[1]];
            var depthGuard = 0;
            while (cur && depthGuard < 32) {
                p = __applyNodeTransform(cur, p, t);
                cur = cur.parent;
                depthGuard++;
            }
            return p;
        }

        function __sampleCompAtTime(comp, t) {
            var layers = [];
            for (var k = 1; k <= comp.numLayers; k++) {
                var lyr = comp.layer(k);
                var isVisual = (!!lyr.hasVideo) && (!lyr.nullLayer) && !(lyr instanceof CameraLayer) && !(lyr instanceof LightLayer);
                var activeAtTime = isVisual && (!!lyr.enabled) && (t >= lyr.inPoint) && (t < lyr.outPoint);

                var tr = lyr.transform;
                var pos = __getPos2D(tr, t);
                var scl = tr && tr.scale ? tr.scale.valueAtTime(t, false) : [100, 100];
                var rot = __getRotDeg(tr, t);

                var sr = { left: 0, top: 0, width: 0, height: 0 };
                try {
                    if (isVisual && typeof lyr.sourceRectAtTime === "function") {
                        sr = lyr.sourceRectAtTime(t, false);
                    }
                } catch (e) {}

                var corners = [
                    [sr.left, sr.top],
                    [sr.left + sr.width, sr.top],
                    [sr.left + sr.width, sr.top + sr.height],
                    [sr.left, sr.top + sr.height]
                ];
                var minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
                for (var c = 0; c < 4; c++) {
                    var worldPt = __layerPointToComp(lyr, corners[c], t);
                    if (worldPt[0] < minX) minX = worldPt[0];
                    if (worldPt[1] < minY) minY = worldPt[1];
                    if (worldPt[0] > maxX) maxX = worldPt[0];
                    if (worldPt[1] > maxY) maxY = worldPt[1];
                }
                var compLeft = isFinite(minX) ? minX : 0;
                var compTop = isFinite(minY) ? minY : 0;
                var compWidth = (isFinite(maxX) && isFinite(minX)) ? Math.max(0, maxX - minX) : 0;
                var compHeight = (isFinite(maxY) && isFinite(minY)) ? Math.max(0, maxY - minY) : 0;

                var textColor = null;
                if (lyr instanceof TextLayer) {
                    try {
                        var td = lyr.property("Source Text").valueAtTime(t, false);
                        if (td && td.applyFill && td.fillColor) {
                            textColor = [td.fillColor[0], td.fillColor[1], td.fillColor[2]];
                        }
                    } catch (te) {}
                }

                var worldCenter = __layerPointToComp(
                    lyr,
                    [sr.left + sr.width / 2.0, sr.top + sr.height / 2.0],
                    t
                );

                layers.push({
                    index: lyr.index,
                    name: lyr.name,
                    enabled: activeAtTime,
                    isText: (lyr instanceof TextLayer),
                    isThreeD: !!lyr.threeDLayer,
                    parentIndex: lyr.parent ? lyr.parent.index : null,
                    textColor: textColor,
                    position: [worldCenter[0], worldCenter[1]],
                    localPosition: [pos[0], pos[1]],
                    scale: [scl[0], scl[1]],
                    rotation: rot,
                    bounds: {
                        left: compLeft,
                        top: compTop,
                        width: compWidth,
                        height: compHeight
                    }
                });
            }

            return {
                name: comp.name,
                width: comp.width,
                height: comp.height,
                timeSeconds: t,
                frameRate: comp.frameRate,
                layers: layers
            };
        }
"""


def _js_target_name(comp_name: str | None) -> str:
    return (
        '"{}"'.format(comp_name.replace("\\", "\\\\").replace('"', '\\"'))
        if comp_name
        else "null"
    )


def _build_geometry_script(comp_name: str | None, time_seconds: float | None) -> str:
    """Build ES3 ExtendScript that extracts parent-aware layer AABB bounds in comp space."""
    target_name = _js_target_name(comp_name)
    target_time = "null" if time_seconds is None else str(float(time_seconds))
    return f"""
        var proj = app.project;
        if (!proj) throw new Error("No open After Effects project.");
        {_ES3_GEOMETRY_HELPERS}
        var comp = __resolveComp(proj, {target_name});
        var t = ({target_time} !== null) ? {target_time} : comp.time;
        return __sampleCompAtTime(comp, t);
    """


def _build_multi_time_geometry_script(
    comp_name: str | None,
    timestamps: list[float] | None,
    sample_count: int = 6,
) -> str:
    """Build ES3 ExtendScript that samples composition geometry across multiple timestamps."""
    target_name = _js_target_name(comp_name)
    count = max(2, min(30, int(sample_count)))
    explicit_js = (
        "[" + ", ".join(str(float(ts)) for ts in timestamps) + "]"
        if timestamps
        else "null"
    )
    return f"""
        var proj = app.project;
        if (!proj) throw new Error("No open After Effects project.");
        {_ES3_GEOMETRY_HELPERS}
        var comp = __resolveComp(proj, {target_name});
        var explicitTimes = {explicit_js};
        var times = [];
        if (explicitTimes !== null && explicitTimes.length > 0) {{
            times = explicitTimes;
        }} else {{
            var startT = comp.workAreaStart;
            var durT = comp.workAreaDuration;
            var maxT = Math.max(0, comp.duration - comp.frameDuration);
            var n = {count};
            for (var s = 0; s < n; s++) {{
                var ratio = (n === 1) ? 0.0 : (s / (n - 1));
                var ts = Math.min(maxT, Math.max(0, startT + durT * ratio));
                times.push(ts);
            }}
        }}
        var snapshots = [];
        for (var idx = 0; idx < times.length; idx++) {{
            snapshots.push(__sampleCompAtTime(comp, times[idx]));
        }}
        return {{ snapshots: snapshots }};
    """


def parse_composition_geometry(raw: dict[str, Any]) -> CompositionGeometry:
    """Convert raw geometry dict into immutable CompositionGeometry domain objects."""
    layers: list[LayerGeometry] = []
    for item in raw.get("layers", []):
        raw_tc = item.get("textColor")
        text_color: tuple[float, float, float] | None = None
        if isinstance(raw_tc, (list, tuple)) and len(raw_tc) >= 3:
            text_color = (float(raw_tc[0]), float(raw_tc[1]), float(raw_tc[2]))

        raw_parent = item.get("parentIndex")
        parent_index = int(raw_parent) if raw_parent is not None else None

        layers.append(
            LayerGeometry(
                index=int(item["index"]),
                name=str(item["name"]),
                enabled=bool(item.get("enabled", True)),
                bounds=Rect(
                    left=float(item["bounds"]["left"]),
                    top=float(item["bounds"]["top"]),
                    width=float(item["bounds"]["width"]),
                    height=float(item["bounds"]["height"]),
                ),
                position=Point2D(
                    float(item.get("position", [0.0, 0.0])[0]),
                    float(item.get("position", [0.0, 0.0])[1]),
                ),
                scale_percent=Point2D(
                    float(item.get("scale", [100.0, 100.0])[0]),
                    float(item.get("scale", [100.0, 100.0])[1]),
                ),
                rotation_deg=float(item.get("rotation", 0.0)),
                is_text=bool(item.get("isText", False)),
                is_three_d=bool(item.get("isThreeD", False)),
                parent_index=parent_index,
                text_color=text_color,
            )
        )

    return CompositionGeometry(
        name=str(raw["name"]),
        width=int(raw["width"]),
        height=int(raw["height"]),
        time_seconds=float(raw.get("timeSeconds", 0.0)),
        frame_rate=float(raw.get("frameRate", 30.0)),
        layers=tuple(layers),
    )


class AfterEffectsGeometryProvider:
    """Fetches composition geometry from After Effects via an injected ScriptRunner."""

    def __init__(self, runner: ScriptRunner) -> None:
        self._runner = runner

    def get_composition_geometry(
        self,
        comp_name: str | None = None,
        time_seconds: float | None = None,
    ) -> CompositionGeometry:
        script = _build_geometry_script(comp_name=comp_name, time_seconds=time_seconds)
        response = self._runner.run(script)
        if not response.get("ok"):
            raise RuntimeError(response.get("error") or "Failed to query AE geometry.")
        result = response.get("result")
        if not isinstance(result, dict):
            raise RuntimeError("After Effects returned empty geometry payload.")
        return parse_composition_geometry(result)

    def get_motion_geometry(
        self,
        comp_name: str | None = None,
        timestamps: list[float] | None = None,
        sample_count: int = 6,
        timeout_seconds: float = 20.0,
    ) -> list[CompositionGeometry]:
        script = _build_multi_time_geometry_script(
            comp_name=comp_name,
            timestamps=timestamps,
            sample_count=sample_count,
        )
        response = self._runner.run(script, timeout_seconds=timeout_seconds)
        if not response.get("ok"):
            raise RuntimeError(response.get("error") or "Failed to query AE motion geometry.")
        result = response.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("snapshots"), list):
            raise RuntimeError("After Effects returned invalid motion geometry payload.")
        return [parse_composition_geometry(snap) for snap in result["snapshots"]]
