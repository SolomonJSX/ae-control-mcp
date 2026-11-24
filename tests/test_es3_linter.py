"""Unit tests for lexical ES3 ExtendScript linter and AEH standard helpers."""

from __future__ import annotations

import unittest

from ae_control_mcp.es3_linter import AE_ES3_STDLIB, lint_es3_script_detailed


class TestEs3Linter(unittest.TestCase):
    def test_aeh_stdlib_is_pure_es3_with_zero_issues(self) -> None:
        issues = lint_es3_script_detailed(AE_ES3_STDLIB)
        self.assertEqual(issues, [])

    def test_ignores_es6_tokens_inside_comments_and_strings(self) -> None:
        code = (
            "// let x = () => `template`; app.project.save();\n"
            "/* const y = items.map(x => x); Object.keys(obj); */\n"
            'var msg = "let a = 1; b => c; arr.forEach(fn); app.project.save();";\n'
            "var single = 'const z = [1, 2, ]; JSON.stringify(z)';\n"
        )
        issues = lint_es3_script_detailed(code)
        self.assertEqual(issues, [])

    def test_detects_es5_es6_and_safety_violations_with_line_numbers(self) -> None:
        code = (
            "let count = 0;\n"
            "var fn = (x) => x + 1;\n"
            "var tpl = `hello`;\n"
            "items.forEach(function (v) {});\n"
            "var keys = Object.keys(obj);\n"
            "var cfg = { a: 1, };\n"
            "app.project.save();\n"
        )
        issues = lint_es3_script_detailed(code)
        by_line = {item.line: item.code for item in issues}
        self.assertEqual(by_line[1], "ES6_LET_CONST")
        self.assertEqual(by_line[2], "ES6_ARROW_FN")
        self.assertEqual(by_line[3], "ES6_TEMPLATE_LITERAL")
        self.assertEqual(by_line[4], "ES5_ARRAY_METHOD")
        self.assertEqual(by_line[5], "ES5_OBJECT_STATIC")
        self.assertEqual(by_line[6], "TRAILING_COMMA")
        self.assertEqual(by_line[7], "FORBIDDEN_PROJECT_SAVE")

    def test_detects_for_of_default_params_and_string_methods(self) -> None:
        code = (
            "function greet(name = 'world') {\n"
            "    if (name.startsWith('w')) return true;\n"
            "    for (var item of list) {}\n"
            "}\n"
        )
        codes = {item.code for item in lint_es3_script_detailed(code)}
        self.assertIn("ES6_DEFAULT_PARAM", codes)
        self.assertIn("ES5_STRING_METHOD", codes)
        self.assertIn("ES6_FOR_OF", codes)

    def test_detects_unbalanced_delimiters(self) -> None:
        code = "function broken() {\n    var arr = [1, 2, 3;\n}\n"
        issues = lint_es3_script_detailed(code)
        codes = [item.code for item in issues]
        self.assertIn("UNBALANCED_DELIMITER", codes)


if __name__ == "__main__":
    unittest.main()
