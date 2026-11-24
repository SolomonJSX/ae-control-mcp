"""Unit tests for GUI safety guards, After Effects hotkey blocking, and screenshot metadata."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from ae_control_mcp import gui


class TestGuiHelpers(unittest.TestCase):
    def test_ensure_within_window_accepts_inside_and_rejects_outside(self) -> None:
        fake_win = SimpleNamespace(
            title="Adobe After Effects 2020",
            left=100,
            top=50,
            width=1200,
            height=800,
            isMinimized=False,
        )
        with mock.patch.object(gui, "_find_window", return_value=fake_win):
            gui._ensure_within_window(500, 400, "After Effects")
            with self.assertRaises(ValueError):
                gui._ensure_within_window(50, 400, "After Effects")

    def test_scroll_mouse_enforces_target_window(self) -> None:
        fake_win = SimpleNamespace(
            title="Adobe After Effects 2020",
            left=100,
            top=100,
            width=800,
            height=600,
            isMinimized=False,
        )
        with (
            mock.patch.object(gui, "_find_window", return_value=fake_win),
            mock.patch("pyautogui.scroll") as scroll_mock,
        ):
            gui.scroll_mouse(-3, x=300, y=300, target_window="After Effects")
            scroll_mock.assert_called_once_with(-3, x=300, y=300)
            with self.assertRaises(ValueError):
                gui.scroll_mouse(-3, x=20, y=20, target_window="After Effects")

    def test_capture_screenshot_rejects_minimized_window(self) -> None:
        fake_win = SimpleNamespace(
            title="Adobe After Effects 2020",
            left=-32000,
            top=-32000,
            width=160,
            height=28,
            isMinimized=True,
        )
        with mock.patch.object(gui, "_find_window", return_value=fake_win):
            with self.assertRaises(ValueError) as ctx:
                gui.capture_screenshot(window_title="After Effects")
        self.assertIn("minimized", str(ctx.exception).lower())

    def test_press_hotkey_rejects_empty_keys(self) -> None:
        with self.assertRaises(ValueError):
            gui.press_hotkey([])
        with self.assertRaises(ValueError):
            gui.press_hotkey(["   "])

    def test_press_hotkey_blocks_save_and_close_in_after_effects_but_allows_undo(self) -> None:
        with (
            mock.patch.object(gui, "_active_window_title", return_value="Adobe After Effects 2020 - untitled.aep"),
            mock.patch("pyautogui.hotkey") as hotkey_mock,
        ):
            with self.assertRaises(PermissionError):
                gui.press_hotkey(["ctrl", "s"])
            with self.assertRaises(PermissionError):
                gui.press_hotkey(["control", "shift", "S"])
            with self.assertRaises(PermissionError):
                gui.press_hotkey(["alt", "f4"])

            gui.press_hotkey(["ctrl", "z"])
            hotkey_mock.assert_called_once_with("ctrl", "z")

    def test_type_text_uses_pyautogui_for_ascii(self) -> None:
        with mock.patch("pyautogui.write") as write_mock:
            gui.type_text("hello", interval=0.02)
        write_mock.assert_called_once_with("hello", interval=0.02)

    def test_type_text_uses_clipboard_for_cyrillic(self) -> None:
        with (
            mock.patch.object(gui, "_win32_get_clipboard_text", return_value="old"),
            mock.patch.object(gui, "_win32_set_clipboard_text", return_value=True) as set_cb,
            mock.patch("pyautogui.hotkey") as hotkey_mock,
            mock.patch("sys.platform", "win32"),
        ):
            gui.type_text("Привет мир")
        hotkey_mock.assert_called_once_with("ctrl", "v")
        self.assertEqual(set_cb.call_args_list[0].args[0], "Привет мир")
        self.assertEqual(set_cb.call_args_list[1].args[0], "old")


if __name__ == "__main__":
    unittest.main()
