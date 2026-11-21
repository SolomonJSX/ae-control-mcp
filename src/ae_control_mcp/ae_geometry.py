"""After Effects 2020 geometry provider using an injected ScriptRunner."""

from __future__ import annotations

from typing import Any

from .geometry.models import CompositionGeometry, LayerGeometry, Point2D, Rect
from .protocols import ScriptRunner


def _build_geometry_script(comp_name: str | None, time_seconds: float | None) -> str:
    """Build ES3 ExtendScript that extracts accurate layer AABB bounds in comp space."""
    target_name = (
        '"{}"'.format(comp_name.replace("\\", "\\\\").replace('"', '\\"'))
        if comp_name
        else "null"
    )
    target_time = "null" if time_seconds is None else str(float(time_seconds))
    return f"""
        var proj = app.project;
        if (!proj) throw new Error("No open After Effects project.");

        var targetName = {target_name};
        var comp = null;
        if (targetName !== null) {{
            for (var i = 1; i <= proj.numItems; i++) {{
                var item = proj.item(i);
                if (item instanceof CompItem && item.name === targetName) {{
                    comp = item;
                    break;
                }}
            }}
        }} else if (proj.activeItem instanceof CompItem) {{
            comp = proj.activeItem;
        }} else {{
            for (var j = 1; j <= proj.numItems; j++) {{
                if (proj.item(j) instanceof CompItem) {{
                    comp = proj.item(j);
                    break;
                }}
            }}
        }}
        if (!comp) throw new Error("Target composition not found.");

        var t = ({target_time} !== null) ? {target_time} : comp.time;
        var layers = [];
        for (var k = 1; k <= comp.numLayers; k++) {{
            var lyr = comp.layer(k);
            var isVisual = (!!lyr.hasVideo) && (!lyr.nullLayer) && !(lyr instanceof CameraLayer) && !(lyr instanceof LightLayer);
            var activeAtTime = isVisual && (!!lyr.enabled) && (t >= lyr.inPoint) && (t < lyr.outPoint);

            var tr = lyr.transform;
            var pos = [0, 0];
            if (tr && tr.position) {{
                if (tr.position.dimensionsSeparated) {{
                    var px = tr.property("ADBE Position_0") ? tr.property("ADBE Position_0").valueAtTime(t, false) : 0;
                    var py = tr.property("ADBE Position_1") ? tr.property("ADBE Position_1").valueAtTime(t, false) : 0;
                    pos = [px, py];
                }} else {{
                    pos = tr.position.valueAtTime(t, false);
                }}
            }}
            var anc = tr && tr.anchorPoint ? tr.anchorPoint.valueAtTime(t, false) : [0, 0];
            var scl = tr && tr.scale ? tr.scale.valueAtTime(t, false) : [100, 100];
            var rot = 0;
            if (tr && tr.rotation) {{
                rot = tr.rotation.valueAtTime(t, false);
            }} else if (tr && tr.zRotation) {{
                rot = tr.zRotation.valueAtTime(t, false);
            }}

            var sr = {{ left: 0, top: 0, width: 0, height: 0 }};
            try {{
                if (isVisual && typeof lyr.sourceRectAtTime === "function") {{
                    sr = lyr.sourceRectAtTime(t, false);
                }}
            }} catch (e) {{}}

            var sx = scl[0] / 100.0;
            var sy = scl[1] / 100.0;
            var rad = rot * Math.PI / 180.0;
            var cosR = Math.cos(rad);
            var sinR = Math.sin(rad);

            var corners = [
                [sr.left, sr.top],
                [sr.left + sr.width, sr.top],
                [sr.left + sr.width, sr.top + sr.height],
                [sr.left, sr.top + sr.height]
            ];
            var minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
            for (var c = 0; c < 4; c++) {{
                var dx = (corners[c][0] - anc[0]) * sx;
                var dy = (corners[c][1] - anc[1]) * sy;
                var wx = pos[0] + dx * cosR - dy * sinR;
                var wy = pos[1] + dx * sinR + dy * cosR;
                if (wx < minX) minX = wx;
                if (wy < minY) minY = wy;
                if (wx > maxX) maxX = wx;
                if (wy > maxY) maxY = wy;
            }}
            var compLeft = isFinite(minX) ? minX : 0;
            var compTop = isFinite(minY) ? minY : 0;
            var compWidth = (isFinite(maxX) && isFinite(minX)) ? Math.max(0, maxX - minX) : 0;
            var compHeight = (isFinite(maxY) && isFinite(minY)) ? Math.max(0, maxY - minY) : 0;

            layers.push({{
                index: lyr.index,
                name: lyr.name,
                enabled: activeAtTime,
                isText: (lyr instanceof TextLayer),
                isThreeD: !!lyr.threeDLayer,
                position: [pos[0], pos[1]],
                scale: [scl[0], scl[1]],
                rotation: rot,
                bounds: {{
                    left: compLeft,
                    top: compTop,
                    width: compWidth,
                    height: compHeight
                }}
            }});
        }}

        return {{
            name: comp.name,
            width: comp.width,
            height: comp.height,
            timeSeconds: t,
            frameRate: comp.frameRate,
            layers: layers
        }};
    """


def parse_composition_geometry(raw: dict[str, Any]) -> CompositionGeometry:
    """Convert raw geometry dict into immutable CompositionGeometry domain objects."""
    layers = tuple(
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
        )
        for item in raw.get("layers", [])
    )
    return CompositionGeometry(
        name=str(raw["name"]),
        width=int(raw["width"]),
        height=int(raw["height"]),
        time_seconds=float(raw.get("timeSeconds", 0.0)),
        frame_rate=float(raw.get("frameRate", 30.0)),
        layers=layers,
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
