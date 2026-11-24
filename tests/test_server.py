"""Unit tests verifying MCP server tool registration."""

from __future__ import annotations

import asyncio
import unittest

from ae_control_mcp import server


class TestServerRegistration(unittest.TestCase):
    def test_expected_tools_are_registered(self) -> None:
        tools = asyncio.run(server.mcp.list_tools())
        names = {t.name for t in tools}

        expected = {
            "take_screenshot",
            "get_screen_info",
            "list_windows",
            "focus_window",
            "mouse_move",
            "mouse_click",
            "mouse_drag",
            "mouse_scroll",
            "keyboard_type",
            "keyboard_hotkey",
            "ae_get_project_info",
            "ae_inspect_composition",
            "ae_audit_project",
            "ae_write_script",
            "ae_cleanup_artifacts",
            "ae_render_frame_preview",
            "ae_render_annotated_preview",
            "ae_render_contact_sheet",
            "ae_render",
            "ae_analyze_layout",
            "ae_analyze_motion",
            "analyze_geometry_layout",
        }
        self.assertTrue(expected.issubset(names), f"Missing tools: {expected - names}")

        removed_mutation_tools = {
            "ae_save_project",
            "ae_run_extendscript",
            "ae_create_composition",
            "ae_import_media",
        }
        self.assertEqual(names & removed_mutation_tools, set())


if __name__ == "__main__":
    unittest.main()
