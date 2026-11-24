"""Unit tests for after_effects read-only inspection, script writing, polling, and aerender."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ae_control_mcp import after_effects
from ae_control_mcp.es3_linter import lint_es3_script_detailed


class TestAfterEffectsHelpers(unittest.TestCase):
    def test_wrap_extendscript_includes_done_sentinel_and_is_valid_es3(self) -> None:
        result_path = Path(r"C:\tmp\result.json")
        done_path = Path(r"C:\tmp\result.done")
        wrapped = after_effects._wrap_extendscript("return { ok: 1 };", result_path, done_path)

        self.assertIn("result.json", wrapped)
        self.assertIn("result.done", wrapped)
        self.assertIn("depth > 12", wrapped)
        self.assertEqual(lint_es3_script_detailed(wrapped), [])

    def test_read_result_when_ready_waits_for_done_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result_path = Path(tmp) / "result.json"
            done_path = Path(tmp) / "result.done"
            result_path.write_text(
                json.dumps({"ok": True, "result": {"title": "Привет"}, "error": None}),
                encoding="utf-8",
            )
            done_path.write_text("1", encoding="utf-8")

            parsed = after_effects._read_result_when_ready(
                result_path=result_path,
                done_path=done_path,
                timeout_seconds=1.0,
            )
            self.assertTrue(parsed["ok"])
            self.assertEqual(parsed["result"]["title"], "Привет")

    def test_read_result_timeout_mentions_scripting_preference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result_path = Path(tmp) / "result.json"
            done_path = Path(tmp) / "result.done"

            parsed = after_effects._read_result_when_ready(
                result_path=result_path,
                done_path=done_path,
                timeout_seconds=0.05,
            )
            self.assertFalse(parsed["ok"])
            self.assertIn("Allow Scripts to Write Files and Access Network", parsed["error"])

    def test_read_result_waits_after_afterfx_handoff_exit_code_1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result_path = Path(tmp) / "result.json"
            done_path = Path(tmp) / "result.done"

            fake_proc = mock.Mock(pid=1234)
            fake_proc.poll.return_value = 1

            calls = 0

            def fake_sleep(_seconds: float) -> None:
                nonlocal calls
                calls += 1
                if calls == 1:
                    result_path.write_text(
                        json.dumps({"ok": True, "result": {"items": 42}, "error": None}),
                        encoding="utf-8",
                    )
                    done_path.write_text("1", encoding="utf-8")

            with mock.patch("time.sleep", side_effect=fake_sleep):
                parsed = after_effects._read_result_when_ready(
                    result_path=result_path,
                    done_path=done_path,
                    timeout_seconds=1.0,
                    proc=fake_proc,
                )

            self.assertTrue(parsed["ok"])
            self.assertEqual(parsed["result"]["items"], 42)

    def test_inspect_composition_and_audit_project_generate_pure_es3(self) -> None:
        captured_scripts: list[str] = []

        def fake_run(script: str, timeout_seconds: float = 15.0) -> dict[str, object]:
            captured_scripts.append(script)
            return {"ok": True, "result": {"compName": "Main"}}

        with mock.patch.object(after_effects, "run_extendscript", side_effect=fake_run):
            after_effects.get_project_info()
            after_effects.inspect_composition(comp_name="Main", layer_index=1, time_seconds=0.5)
            after_effects.audit_project()

        self.assertEqual(len(captured_scripts), 3)
        for idx, script in enumerate(captured_scripts):
            issues = lint_es3_script_detailed(script)
            self.assertEqual(issues, [], f"Script #{idx} had ES3 lint issues: {issues}")

        self.assertIn("ADBE Effect Parade", captured_scripts[1])
        self.assertIn("Source Text", captured_scripts[1])
        self.assertIn("expressionError", captured_scripts[2])
        self.assertIn("footageMissing", captured_scripts[2])

    def test_render_composition_builds_expected_aerender_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "demo.aep"
            proj.write_bytes(b"fake-aep")
            out = Path(tmp) / "nested" / "video.mp4"

            completed = mock.Mock(returncode=0, stdout="RENDER OK", stderr="")
            with (
                mock.patch.object(
                    after_effects,
                    "find_ae_executable",
                    return_value=Path(r"C:\AE\aerender.exe"),
                ),
                mock.patch("subprocess.run", return_value=completed) as run_mock,
            ):
                res = after_effects.render_composition(
                    project_path=str(proj),
                    comp_name="MainComp",
                    output_path=str(out),
                    render_settings="Best Settings",
                    output_module="Lossless",
                    start_frame=0,
                    end_frame=150,
                    sound=False,
                )

            self.assertTrue(res["ok"])
            self.assertTrue(out.parent.is_dir())
            cmd = run_mock.call_args.args[0]
            self.assertEqual(cmd[0], r"C:\AE\aerender.exe")
            self.assertIn("-comp", cmd)
            self.assertIn("MainComp", cmd)
            self.assertIn("OFF", cmd)

    def test_save_frame_preview_waits_for_async_png(self) -> None:
        from PIL import Image as PilImage

        created_paths: list[Path] = []

        def fake_run(script: str, timeout_seconds: float = 20.0) -> dict[str, object]:
            marker = 'new File("'
            start = script.index(marker) + len(marker)
            end = script.index('")', start)
            png_path = Path(script[start:end].replace("\\\\", "\\"))
            created_paths.append(png_path)
            return {
                "ok": True,
                "result": {
                    "compName": "Main",
                    "timeSeconds": 1.0,
                    "frameRate": 30.0,
                    "width": 64,
                    "height": 64,
                    "exists": False,
                },
            }

        sleep_calls = 0

        def fake_sleep(_seconds: float) -> None:
            nonlocal sleep_calls
            sleep_calls += 1
            if sleep_calls == 2 and created_paths:
                PilImage.new("RGB", (64, 64), color=(10, 20, 30)).save(created_paths[0], format="PNG")

        with (
            mock.patch.object(after_effects, "run_extendscript", side_effect=fake_run),
            mock.patch("time.sleep", side_effect=fake_sleep),
        ):
            preview = after_effects.save_frame_preview(comp_name="Main", time_seconds=1.0, timeout_seconds=2.0)

        self.assertEqual(preview.comp_name, "Main")
        self.assertEqual(preview.width, 64)
        self.assertEqual(preview.height, 64)
        self.assertGreater(len(preview.image_bytes), 0)

    def test_write_extendscript_file_stdlib_and_strict_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            # 1) Strict mode blocks ES6/save errors without writing file
            bad_out = Path(tmp) / "bad_script.jsx"
            bad_res = after_effects.write_extendscript_file(
                output_path=str(bad_out),
                script_code="let x = 1;\napp.project.save();",
                undo_group_name="Bad Script",
                strict=True,
            )
            self.assertFalse(bad_res["ok"])
            self.assertFalse(bad_res["written"])
            self.assertFalse(bad_out.exists())
            self.assertGreaterEqual(len(bad_res["issues"]), 2)

            # 2) Valid ES3 + include_stdlib=True passes strict mode cleanly
            good_out = Path(tmp) / "scripts" / "animate_banner"
            good_res = after_effects.write_extendscript_file(
                output_path=str(good_out),
                script_code=(
                    'var comp = AEH.findComp("Main");\n'
                    'var txt = AEH.addText(comp, "Привет", 72, AEH.hexToRgb("#38BDF8"));\n'
                ),
                undo_group_name="Animate Banner",
                include_stdlib=True,
                strict=True,
            )
            self.assertTrue(good_res["ok"])
            self.assertTrue(good_res["written"])
            self.assertTrue(good_res["included_stdlib"])
            self.assertEqual(good_res["warnings"], [])
            written = Path(good_res["path"])
            self.assertTrue(written.read_bytes().startswith(b"\xef\xbb\xbf"))
            text = written.read_text(encoding="utf-8-sig")
            self.assertIn("var AEH =", text)
            self.assertIn('app.beginUndoGroup("Animate Banner")', text)

    def test_cleanup_artifacts_removes_screenshots_and_junk_but_protects_scripts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            keep_script = root / "my_animation.jsx"
            keep_project = root / "scene.aep"
            keep_asset = root / "map_texture.png"
            del_screenshot = root / "screenshot_01.png"
            del_sheet = root / "contact_sheet_main.jpg"
            del_tmp = root / "debug.tmp"

            for f in (keep_script, keep_project, keep_asset, del_screenshot, del_sheet, del_tmp):
                f.write_bytes(b"12345")

            real = after_effects.cleanup_artifacts(
                target_dir=str(root),
                extra_paths=[str(keep_script)],
                clean_temp=False,
                dry_run=False,
            )
            self.assertTrue(real["ok"])
            self.assertTrue(keep_script.exists())
            self.assertTrue(keep_project.exists())
            self.assertTrue(keep_asset.exists())
            self.assertFalse(del_screenshot.exists())
            self.assertFalse(del_sheet.exists())
            self.assertFalse(del_tmp.exists())


if __name__ == "__main__":
    unittest.main()
