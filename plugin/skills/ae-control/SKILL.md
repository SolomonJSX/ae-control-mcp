---
name: ae-control
description: How to inspect Adobe After Effects 2020 projects read-only, write safe ES3 .jsx scripts for manual execution, clean up temporary screenshots/junk files, and render via aerender using ae-control-mcp tools.
---

# Adobe After Effects 2020 — Safe Script-Only Workflow

Use this workflow whenever working with **Adobe After Effects 2020**. The plugin is intentionally **read-only against the live `.aep` project**: it NEVER directly mutates or saves the `.aep` file, so accidental edits can never overwrite the user's saved project.

## 0. Prerequisites in After Effects 2020
If read-only inspection (`ae_get_project_info` / `ae_analyze_layout` / `ae_render_frame_preview`) times out, verify with the user that:
1. Adobe After Effects 2020 is open and no modal dialog is blocking execution.
2. **Edit -> Preferences -> Scripting & Expressions -> "Allow Scripts to Write Files and Access Network"** is **checked**.

## 1. Recommended Workflow (Inspect -> Write `.jsx` -> User Runs -> Cleanup)
1. **Inspect (Read-Only):**
   - Call `ae_get_project_info` to see exact composition names, layer names, types, and timings.
   - Call `ae_analyze_layout(comp_name, time_seconds)` to inspect layer bounds, safe zones, and overlaps.
   - Call `ae_render_frame_preview(comp_name, time_seconds)` (or `take_screenshot`) if visual context is needed.
2. **Write the `.jsx` Script (`ae_write_script`):**
   - Generate a clean, self-contained ES3 ExtendScript file via `ae_write_script(output_path, script_code, undo_group_name="...")`.
   - `ae_write_script` saves UTF-8 with BOM (so AE 2020 decodes Cyrillic properly), wraps code in `app.beginUndoGroup(...)` / `try...catch...finally`, checks for ES6+ mistakes, and **never executes or saves the `.aep`**.
   - Check the returned `warnings` list — if any ES6+ or `app.project.save()` warning is reported, fix the script and rewrite it.
3. **Hand Off to the User:**
   - Give the user the exact path to the `.jsx` file so they can apply it manually in After Effects via **File -> Scripts -> Run Script File...**.
   - Remind them they can undo the entire script in one step with `Ctrl+Z` if anything looks off, and save (`Ctrl+S`) only when satisfied.
4. **Clean Up Temporary Files (`ae_cleanup_artifacts`):**
   - Call `ae_cleanup_artifacts(target_dir=..., clean_temp=True)` to delete leftover screenshots, frame previews, and temporary `ae_mcp_*` / `ae_frame_*` folders.
   - Protected extensions (`.jsx`, `.jsxbin`, `.aep`, `.aepx`, `.prproj`, `.psd`, `.ai`, `.ffx`) are **never** deleted.

## 2. Strict ES3 ExtendScript Rules for AE 2020
After Effects 2020 ExtendScript uses **ES3 JavaScript**:
- **DO:** Use `var`, `function`, standard `for (var i = 0; i < n; i++)` loops, and wrap edits in `app.beginUndoGroup("..."); try { ... } finally { app.endUndoGroup(); }`.
- **DO NOT:** Use `let`, `const`, arrow functions (`=>`), template literals (`` `...` ``), destructuring, `Array.prototype.map/forEach`, `JSON.stringify`, or `app.project.save()`.
- **Centering a Text Layer cleanly:**
  ```javascript
  var txt = comp.layers.addText("Заголовок");
  var doc = txt.property("Source Text").value;
  doc.fontSize = 84;
  doc.fillColor = [1, 1, 1];
  doc.justification = ParagraphJustification.CENTER_JUSTIFY;
  txt.property("Source Text").setValue(doc);
  var r = txt.sourceRectAtTime(0, false);
  txt.transform.anchorPoint.setValue([r.left + r.width / 2, r.top + r.height / 2]);
  txt.transform.position.setValue([comp.width / 2, comp.height / 2]);
  ```
- **Adding Smooth Keyframes (Easy Ease):**
  ```javascript
  var op = layer.transform.opacity;
  op.setValueAtTime(0.0, 0);
  op.setValueAtTime(0.6, 100);
  var ease = new KeyframeEase(0, 75);
  op.setTemporalEaseAtKey(1, [ease], [ease]);
  op.setTemporalEaseAtKey(2, [ease], [ease]);
  ```

## 3. Headless Render (Optional)
- Only when the user explicitly asks to render an already-saved `.aep` file, call `ae_render(project_path, comp_name, output_path, ...)` via `aerender.exe`.

## 4. GUI Mouse & Keyboard Tools (Inspection / Fallback)
- Use `list_windows` and `take_screenshot(window_title="After Effects")` for visual inspection.
- Never send `Ctrl+S` or save/overwrite the project via `keyboard_hotkey`.
- If clicking is ever explicitly needed, convert local image coordinates `(ix, iy)` via `screen_x = round(ix * scale_x) + offset_x`, `screen_y = round(iy * scale_y) + offset_y`, and pass `target_window="After Effects"`.
