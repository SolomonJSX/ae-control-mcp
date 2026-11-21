"""Unit tests for GUI safety guards, hotkeys, and screenshot metadata."""

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
