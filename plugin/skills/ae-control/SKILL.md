---
name: ae-control
description: How to inspect Adobe After Effects 2020 projects read-only, audit health/expressions, analyze spatial & motion layouts (including 9:16 Reels/Shorts), render contact sheets & annotated previews, write safe ES3 .jsx scripts with AEH helpers, and clean up temporary artifacts.
---

# Adobe After Effects 2020 — Safe Script-First Workflow (v0.4)

Use this workflow whenever working with **Adobe After Effects 2020**. The plugin is strictly **read-only against the live `.aep` project**: it NEVER directly mutates or saves the `.aep` file.

## 0. Prerequisites in After Effects 2020
If read-only inspection times out, verify with the user that:
1. Adobe After Effects 2020 is open and no modal dialog is blocking execution.
2. **Edit -> Preferences -> Scripting & Expressions -> "Allow Scripts to Write Files and Access Network"** is **checked**.

## 1. Recommended Workflow (Inspect -> Visual/Layout Check -> Write `.jsx` -> User Runs -> Cleanup)

1. **Inspect & Audit (Read-Only):**
   - `ae_get_project_info()` — quick overview of compositions, layer types (`text`, `shape`, `precomp`, `solid`, `av`, `null`, `camera`, `light`), and timings.
   - `ae_inspect_composition(comp_name, layer_index, layer_name, time_seconds)` — deep inspection of text styles (`font`, `fontSize`, `fillColor`, `tracking`), transform values & keyframe ranges, expressions, effects (`matchName`), and markers.
   - `ae_audit_project()` — project-wide health check for missing footage, broken expressions (`expressionError`), fonts used, unused assets, and render templates.
2. **Spatial, Motion & Visual Verification:**
   - `ae_analyze_layout(comp_name, time_seconds, preset)` — parent-aware AABB check. Use `preset="social_vertical"` for **9:16 Reels / TikTok / Shorts** or `preset="full"` to include near-miss alignment checks.
   - `ae_analyze_motion(comp_name, sample_count=6, preset=...)` — checks layout rules across the timeline in a single AE round-trip to catch clipping/obstructions mid-animation.
   - `ae_render_annotated_preview(comp_name, time_seconds, preset=..., check_contrast=True)` — renders the frame with color-coded bounding boxes, safe-zone overlays, and WCAG text-contrast checks.
   - `ae_render_contact_sheet(comp_name, num_frames=6, columns=3)` — renders a multi-frame storyboard grid with timecodes to inspect animation pacing and transitions in one image.
3. **Write Safe ES3 `.jsx` Script (`ae_write_script`):**
   - Call `ae_write_script(output_path, script_code, undo_group_name="...", include_stdlib=True, strict=True)`.
   - When `include_stdlib=True`, the `AEH` helper object is injected automatically:
     - `AEH.findComp(name)` — find comp by name, `activeItem`, or first comp.
     - `AEH.hexToRgb("#FF5500")` — convert hex string to `[r, g, b]` in `0..1`.
     - `AEH.centerAnchor(layer, timeSec)` — center anchor point via `sourceRectAtTime` while compensating position.
     - `AEH.easyEase(prop, influence)` — apply `KeyframeEase` safely across 1D, 2D, and 3D properties without dimension-mismatch errors.
     - `AEH.addText(comp, content, fontSize, rgbColor, posXY)` — create centered text layer cleanly.
   - If `strict=True` returns `ok: false`, inspect `issues` (with 1-based line numbers), fix every ES3/safety issue, and call `ae_write_script` again.
4. **Hand Off & Cleanup:**
   - Give the user the `.jsx` path to run via **File -> Scripts -> Run Script File...** (`Ctrl+Z` undoes everything in one step).
   - Call `ae_cleanup_artifacts(target_dir=..., clean_temp=True)` when finished to remove temporary screenshots and frame previews while preserving `.jsx` and `.aep` files.

## 2. Reference Guides (Load On Demand)
- Read `references/es3-pitfalls.md` for tricky ExtendScript ES3 edge cases (`KeyframeEase` array dimensions, separated XYZ positions, `ShapeLayer` group hierarchies, `TextDocument`).
- Read `references/common-matchnames.md` for universal `ADBE` effect and shape matchNames that work identically in **Russian and English** After Effects 2020 locales.
