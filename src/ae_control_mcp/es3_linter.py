"""Lexical ES3 ExtendScript linter and AEH standard helper library for After Effects 2020."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Literal

AE_ES3_STDLIB = """// --- AE Control ES3 Standard Helpers (AEH) ---
var AEH = (function () {
    function findComp(name) {
        var proj = app.project;
        if (!proj) throw new Error("No open After Effects project.");
        if (name) {
            for (var i = 1; i <= proj.numItems; i++) {
                var it = proj.item(i);
                if (it instanceof CompItem && it.name === name) return it;
            }
            throw new Error("Composition not found: " + name);
        }
        if (proj.activeItem instanceof CompItem) return proj.activeItem;
        for (var j = 1; j <= proj.numItems; j++) {
            if (proj.item(j) instanceof CompItem) return proj.item(j);
        }
        throw new Error("No composition found in project.");
    }

    function hexToRgb(hex) {
        var s = String(hex).replace(/^#/, "");
        if (s.length === 3) {
            s = s.charAt(0) + s.charAt(0) + s.charAt(1) + s.charAt(1) + s.charAt(2) + s.charAt(2);
        }
        var num = parseInt(s, 16);
        if (isNaN(num)) return [1, 1, 1];
        return [((num >> 16) & 255) / 255.0, ((num >> 8) & 255) / 255.0, (num & 255) / 255.0];
    }

    function centerAnchor(layer, timeSec) {
        var t = (timeSec !== undefined && timeSec !== null) ? timeSec : 0;
        if (typeof layer.sourceRectAtTime !== "function") return;
        var r = layer.sourceRectAtTime(t, false);
        var cx = r.left + r.width / 2.0;
        var cy = r.top + r.height / 2.0;
        var anc = layer.transform.anchorPoint;
        var pos = layer.transform.position;
        var oldAnc = anc.numKeys > 0 ? anc.valueAtTime(t, false) : anc.value;
        var dx = cx - oldAnc[0];
        var dy = cy - oldAnc[1];
        if (anc.numKeys === 0) {
            anc.setValue(oldAnc.length > 2 ? [cx, cy, oldAnc[2]] : [cx, cy]);
        }
        if (pos && !pos.dimensionsSeparated && pos.numKeys === 0) {
            var oldPos = pos.value;
            var scl = layer.transform.scale.value;
            var nx = oldPos[0] + dx * (scl[0] / 100.0);
            var ny = oldPos[1] + dy * (scl[1] / 100.0);
            pos.setValue(oldPos.length > 2 ? [nx, ny, oldPos[2]] : [nx, ny]);
        }
    }

    function easyEase(prop, influence) {
        if (!prop || prop.numKeys < 1) return;
        var inf = (influence !== undefined && influence !== null) ? influence : 75;
        var ease = new KeyframeEase(0, inf);
        var dims = 1;
        var vt = prop.propertyValueType;
        if (vt === PropertyValueType.TwoD) dims = 2;
        else if (vt === PropertyValueType.ThreeD) dims = 3;
        var easeArr = [];
        for (var d = 0; d < dims; d++) easeArr.push(ease);
        for (var k = 1; k <= prop.numKeys; k++) {
            prop.setTemporalEaseAtKey(k, easeArr, easeArr);
        }
    }

    function addText(comp, content, fontSize, rgbColor, posXY) {
        var lyr = comp.layers.addText(String(content));
        var src = lyr.property("Source Text");
        var doc = src.value;
        if (fontSize) doc.fontSize = fontSize;
        if (rgbColor) doc.fillColor = rgbColor;
        doc.justification = ParagraphJustification.CENTER_JUSTIFY;
        src.setValue(doc);
        var r = lyr.sourceRectAtTime(comp.time, false);
        lyr.transform.anchorPoint.setValue([r.left + r.width / 2.0, r.top + r.height / 2.0]);
        lyr.transform.position.setValue(posXY || [comp.width / 2.0, comp.height / 2.0]);
        return lyr;
    }

    return {
        findComp: findComp,
        hexToRgb: hexToRgb,
        centerAnchor: centerAnchor,
        easyEase: easyEase,
        addText: addText
    };
})();
"""


@dataclass(frozen=True)
class LintIssue:
    line: int
    code: str
    severity: Literal["error", "warning"]
    message: str

    def format_warning(self) -> str:
        return f"Line {self.line} [{self.code}]: {self.message}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def strip_comments_and_strings(source: str) -> tuple[str, list[int]]:
    """Replace JS comments and quoted string contents with spaces, preserving newlines.

    Returns (sanitized_code, template_backtick_lines) so regex rules never match inside
    strings or comments while exact 1-based line numbers are preserved.
    """
    out: list[str] = []
    backtick_lines: list[int] = []
    i = 0
    n = len(source)
    line = 1

    while i < n:
        ch = source[i]
        nxt = source[i + 1] if i + 1 < n else ""

        if ch == "\n":
            out.append("\n")
            line += 1
            i += 1
            continue

        # Line comment //
        if ch == "/" and nxt == "/":
            while i < n and source[i] != "\n":
                out.append(" ")
                i += 1
            continue

        # Block comment /* ... */
        if ch == "/" and nxt == "*":
            out.append("  ")
            i += 2
            while i < n:
                if source[i] == "*" and i + 1 < n and source[i + 1] == "/":
                    out.append("  ")
                    i += 2
                    break
                if source[i] == "\n":
                    out.append("\n")
                    line += 1
                else:
                    out.append(" ")
                i += 1
            continue

        # Single or double quoted string
        if ch in ('"', "'"):
            quote = ch
            out.append(quote)
            i += 1
            while i < n:
                c = source[i]
                if c == "\\" and i + 1 < n:
                    out.append("  ")
                    if source[i + 1] == "\n":
                        line += 1
                    i += 2
                    continue
                if c == quote:
                    out.append(quote)
                    i += 1
                    break
                if c == "\n":
                    out.append("\n")
                    line += 1
                else:
                    out.append(" ")
                i += 1
            continue

        # ES6 template literal `...`
        if ch == "`":
            backtick_lines.append(line)
            out.append(" ")
            i += 1
            while i < n:
                c = source[i]
                if c == "\\" and i + 1 < n:
                    out.append("  ")
                    if source[i + 1] == "\n":
                        line += 1
                    i += 2
                    continue
                if c == "`":
                    out.append(" ")
                    i += 1
                    break
                if c == "\n":
                    out.append("\n")
                    line += 1
                else:
                    out.append(" ")
                i += 1
            continue

        out.append(ch)
        i += 1

    return "".join(out), backtick_lines


_LINE_PATTERNS: tuple[tuple[re.Pattern[str], str, Literal["error", "warning"], str], ...] = (
    (
        re.compile(r"\b(?:let|const)\s+[A-Za-z_$]"),
        "ES6_LET_CONST",
        "error",
        "Detected 'let'/'const' (ES6+); AE 2020 ExtendScript requires 'var'.",
    ),
    (
        re.compile(r"=>"),
        "ES6_ARROW_FN",
        "error",
        "Detected arrow function '=>' (ES6+); AE 2020 requires 'function (...) {}'.",
    ),
    (
        re.compile(r"\bfor\s*\(\s*(?:var|let|const)?\s*[A-Za-z_$][\w$]*\s+of\b"),
        "ES6_FOR_OF",
        "error",
        "Detected 'for...of' loop (ES6+); use standard indexed 'for (var i = 0; i < n; i++)'.",
    ),
    (
        re.compile(r"\bfunction\s*[A-Za-z_$]*\s*\([^)]*(?<![=!<>])=(?![=>])[^)]*\)"),
        "ES6_DEFAULT_PARAM",
        "error",
        "Detected default parameter in function signature (ES6+); check 'if (arg === undefined)' inside body.",
    ),
    (
        re.compile(
            r"\.(?:forEach|map|filter|reduce|reduceRight|some|every|find|findIndex|includes|flat|flatMap)\s*\("
        ),
        "ES5_ARRAY_METHOD",
        "error",
        "Detected ES5+ Array method (.forEach/.map/.filter/etc.), which does not exist in AE 2020 ES3; use a 'for' loop.",
    ),
    (
        re.compile(r"\.(?:startsWith|endsWith|padStart|padEnd|repeat|trimStart|trimEnd)\s*\("),
        "ES5_STRING_METHOD",
        "error",
        "Detected ES6+ String method (.startsWith/.endsWith/.repeat/etc.); use indexOf() or RegExp in ES3.",
    ),
    (
        re.compile(
            r"\b(?:Object\.(?:keys|values|entries|assign|freeze|create)|Array\.(?:isArray|from))\s*\("
        ),
        "ES5_OBJECT_STATIC",
        "error",
        "Detected ES5+ Object/Array static helper (Object.keys/assign/Array.isArray), unavailable in AE 2020 ES3.",
    ),
    (
        re.compile(r"\bJSON\.(?:stringify|parse)\s*\("),
        "NO_NATIVE_JSON",
        "error",
        "Detected 'JSON.stringify'/'JSON.parse', which do not exist in AE 2020 ExtendScript.",
    ),
    (
        re.compile(r"\bapp\.project\.(?:save|saveWithDialog|close)\s*\("),
        "FORBIDDEN_PROJECT_SAVE",
        "error",
        "Detected 'app.project.save()/close()'; scripts must never auto-save or close the user's .aep project.",
    ),
    (
        re.compile(r"\b(?:system\.callSystem|app\.quit)\s*\("),
        "FORBIDDEN_SYSTEM_CALL",
        "warning",
        "Detected 'system.callSystem()' or 'app.quit()'; avoid shell execution or quitting AE from scripts.",
    ),
)

_TRAILING_COMMA_RE = re.compile(r",(\s*)[}\]]")


def _line_of_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _check_balanced_delimiters(sanitized: str) -> list[LintIssue]:
    pairs = {"(": ")", "[": "]", "{": "}"}
    closers = {")": "(", "]": "[", "}": "{"}
    stack: list[tuple[str, int]] = []
    issues: list[LintIssue] = []
    line = 1

    for ch in sanitized:
        if ch == "\n":
            line += 1
            continue
        if ch in pairs:
            stack.append((ch, line))
        elif ch in closers:
            if not stack:
                issues.append(
                    LintIssue(
                        line=line,
                        code="UNBALANCED_DELIMITER",
                        severity="error",
                        message=f"Unexpected closing '{ch}' with no matching '{closers[ch]}'.",
                    )
                )
            else:
                top_ch, top_line = stack.pop()
                if top_ch != closers[ch]:
                    issues.append(
                        LintIssue(
                            line=line,
                            code="UNBALANCED_DELIMITER",
                            severity="error",
                            message=(
                                f"Mismatched closing '{ch}'; expected '{pairs[top_ch]}' "
                                f"to match '{top_ch}' opened on line {top_line}."
                            ),
                        )
                    )

    for open_ch, open_line in stack:
        issues.append(
            LintIssue(
                line=open_line,
                code="UNBALANCED_DELIMITER",
                severity="error",
                message=f"Unclosed '{open_ch}' (missing '{pairs[open_ch]}').",
            )
        )
    return issues


def lint_es3_script_detailed(script_code: str) -> list[LintIssue]:
    """Run lexical ES3 + AE safety checks on ExtendScript source code."""
    sanitized, backtick_lines = strip_comments_and_strings(script_code)
    issues: list[LintIssue] = []

    for bt_line in sorted(set(backtick_lines)):
        issues.append(
            LintIssue(
                line=bt_line,
                code="ES6_TEMPLATE_LITERAL",
                severity="error",
                message="Detected template literal backtick '`' (ES6+); use string concatenation '+'.",
            )
        )

    lines = sanitized.splitlines()
    for idx, line_text in enumerate(lines, start=1):
        for pattern, code, severity, message in _LINE_PATTERNS:
            if pattern.search(line_text):
                issues.append(LintIssue(line=idx, code=code, severity=severity, message=message))

    for match in _TRAILING_COMMA_RE.finditer(sanitized):
        ln = _line_of_offset(sanitized, match.start())
        issues.append(
            LintIssue(
                line=ln,
                code="TRAILING_COMMA",
                severity="warning",
                message="Detected trailing comma before '}' or ']'; AE 2020 ES3 parser may reject trailing commas.",
            )
        )

    issues.extend(_check_balanced_delimiters(sanitized))
    issues.sort(key=lambda item: (item.line, 0 if item.severity == "error" else 1, item.code))
    return issues
