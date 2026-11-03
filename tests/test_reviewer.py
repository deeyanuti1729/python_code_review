import json
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET
import zipfile
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reviewer import CATEGORIES, PythonReview, _render_text
from web_app import (
    GeminiConfigurationError,
    GeminiUpstreamError,
    create_code_docx,
    create_prompts_docx,
    generate_correction,
    review_payload,
    run_payload,
)


class PythonReviewTests(unittest.TestCase):
    def test_detects_multiple_ast_findings(self) -> None:
        source = """
def collect(items=[]):
    try:
        for item in items:
            cursor.execute(f"SELECT * FROM items WHERE id={item}")
    except:
        pass
"""
        findings = PythonReview().review(source)
        issues = {(finding.category, finding.severity) for finding in findings}
        self.assertIn(("Bugs & Logic", "Medium"), issues)
        self.assertIn(("Security", "High"), issues)
        self.assertIn(("Performance", "Medium"), issues)

    def test_detects_shell_and_tls_configuration(self) -> None:
        source = """
import requests
import subprocess
command = ["echo", "hello"]
url = "https://example.com"
subprocess.run(command, shell=True)
requests.get(url, verify=False)
"""
        findings = PythonReview().review(source)
        self.assertEqual(
            [finding.category for finding in findings if finding.category == "Security"],
            ["Security", "Security"],
        )

    def test_detects_silently_ignored_specific_exception(self) -> None:
        findings = PythonReview().review(
            "value = 'invalid'\ntry:\n    int(value)\nexcept ValueError:\n    pass\n"
        )
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].category, "Edge Cases")

    def test_detects_potential_undefined_names_at_module_and_function_scope(self) -> None:
        findings = PythonReview().review(
            "print(hello)\n"
            "def greet(name):\n"
            "    return greeting + name\n"
        )
        undefined = {
            finding.issue
            for finding in findings
            if "not defined" in finding.issue
        }
        self.assertEqual(len(undefined), 2)
        self.assertTrue(any("`hello`" in issue for issue in undefined))
        self.assertTrue(any("`greeting`" in issue for issue in undefined))

    def test_does_not_flag_builtins_imports_or_defined_globals(self) -> None:
        findings = PythonReview().review(
            "import math\n"
            "message = 'hello'\n"
            "def area(radius):\n"
            "    return math.pi * radius ** 2 + len(message)\n"
        )
        self.assertFalse(any("not defined" in finding.issue for finding in findings))

    def test_handles_comprehension_scope_and_finds_unknown_global(self) -> None:
        findings = PythonReview().review("[item + missing for item in items]")
        undefined = [finding.issue for finding in findings if "not defined" in finding.issue]
        self.assertEqual(len(undefined), 2)
        self.assertTrue(any("`missing`" in issue for issue in undefined))
        self.assertTrue(any("`items`" in issue for issue in undefined))

    def test_compiler_context_errors_are_reported(self) -> None:
        report = review_payload({"source": "return 1\n"})
        self.assertEqual(report["syntax_error"]["message"], "'return' outside function")

    def test_run_payload_returns_program_output(self) -> None:
        result = run_payload({"source": "print('hello from Python')"})
        self.assertEqual(result["stdout"].splitlines(), ["hello from Python"])
        self.assertEqual(result["stderr"], "")
        self.assertEqual(result["exit_code"], 0)
        self.assertFalse(result["timed_out"])
        self.assertFalse(result["truncated"])

    def test_run_payload_does_not_pass_gemini_api_key(self) -> None:
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            result = run_payload(
                {"source": "import os; print('GEMINI_API_KEY' in os.environ)"}
            )
        self.assertEqual(result["stdout"].strip(), "False")

    def test_run_payload_returns_runtime_errors(self) -> None:
        result = run_payload({"source": "raise ValueError('bad input')"})
        self.assertEqual(result["stdout"], "")
        self.assertIn("ValueError: bad input", result["stderr"])
        self.assertEqual(result["exit_code"], 1)

    def test_run_payload_limits_captured_output(self) -> None:
        result = run_payload({"source": "print('x' * 300_000)"})
        self.assertTrue(result["truncated"])
        self.assertLessEqual(len(result["stdout"].encode("utf-8")), 256_000)

    def test_run_payload_rejects_empty_and_oversized_source(self) -> None:
        with self.assertRaisesRegex(ValueError, "Enter Python code"):
            run_payload({"source": "  "})
        with self.assertRaisesRegex(ValueError, "100,000 characters or fewer"):
            run_payload({"source": "x" * 100_001})

    def test_diff_scans_only_added_lines_and_tracks_line_numbers(self) -> None:
        diff = """--- a/app.py
+++ b/app.py
@@ -3,1 +3,2 @@
 safe_call()
+eval(user_input)
"""
        findings = PythonReview().review(diff, is_diff=True)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].line, 4)
        self.assertEqual(findings[0].category, "Security")

    def test_clean_report_mentions_all_categories(self) -> None:
        report = _render_text([])
        for category in CATEGORIES:
            self.assertIn(category, report)
        self.assertEqual(report.count("No issues found"), len(CATEGORIES))

    def test_json_output_is_valid_and_has_all_categories(self) -> None:
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, str(root / "reviewer.py"), "--format", "json"],
            input="print('ok')\n",
            text=True,
            capture_output=True,
            check=True,
        )
        payload = json.loads(result.stdout)
        self.assertEqual(set(payload["categories"]), set(CATEGORIES))

    def test_web_review_reports_syntax_errors(self) -> None:
        report = review_payload({"source": "def broken(:\n    pass\n"})
        self.assertEqual(report["syntax_error"]["line"], 1)
        self.assertEqual(report["syntax_error"]["message"], "invalid syntax")
        self.assertEqual(set(report["categories"]), set(CATEGORIES))

    def test_web_review_handles_diff_without_syntax_error(self) -> None:
        report = review_payload(
            {"source": "@@ -1 +1 @@\n+eval(value)\n", "mode": "diff"}
        )
        self.assertIsNone(report["syntax_error"])
        self.assertEqual(report["findings"][0]["category"], "Security")

    def test_web_review_rejects_invalid_mode_and_oversized_source(self) -> None:
        with self.assertRaisesRegex(ValueError, "Mode must be"):
            review_payload({"source": "print('ok')", "mode": "javascript"})
        with self.assertRaisesRegex(ValueError, "characters or fewer"):
            review_payload({"source": "x" * 1_000_001})

    def test_docx_export_contains_valid_prompt_document(self) -> None:
        content = create_prompts_docx(
            {
                "prompts": [
                    {"title": "Review & improve", "text": "Check <security>.\nKeep it safe."},
                    {"title": "", "text": "Another prompt"},
                ]
            }
        )

        with zipfile.ZipFile(BytesIO(content)) as archive:
            document = ET.fromstring(archive.read("word/document.xml"))
        text = [
            node.text
            for node in document.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")
        ]
        self.assertIn("Review & improve", text)
        self.assertIn("Check <security>.", text)
        self.assertIn("Keep it safe.", text)
        self.assertIn("Prompt 2", text)

    def test_docx_export_rejects_invalid_prompt_payloads(self) -> None:
        with self.assertRaisesRegex(ValueError, "between 1 and"):
            create_prompts_docx({"prompts": []})
        with self.assertRaisesRegex(ValueError, "non-empty text"):
            create_prompts_docx({"prompts": [{"title": "Empty", "text": "  "}]})

    def test_code_docx_export_preserves_code_lines_and_indentation(self) -> None:
        content = create_code_docx(
            {"source": "def greet(name):\r\n    print(f'Hello, {name}')\r\n"}
        )
        with zipfile.ZipFile(BytesIO(content)) as archive:
            document = ET.fromstring(archive.read("word/document.xml"))
        namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        paragraphs = [
            "".join(node.text or "" for node in paragraph.iter(f"{namespace}t"))
            for paragraph in document.iter(f"{namespace}p")
        ]
        self.assertIn("Corrected code", paragraphs)
        self.assertIn("def greet(name):", paragraphs)
        self.assertIn("    print(f'Hello, {name}')", paragraphs)
        self.assertEqual(paragraphs[-1], "")

    def test_code_docx_export_rejects_empty_and_oversized_source(self) -> None:
        with self.assertRaisesRegex(ValueError, "Paste corrected code"):
            create_code_docx({"source": " "})
        with self.assertRaisesRegex(ValueError, "1,000,000 characters or fewer"):
            create_code_docx({"source": "x" * 1_000_001})

    def test_gemini_correction_strips_fences_and_checks_syntax(self) -> None:
        response_body = json.dumps(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "findings": [
                                                {
                                                    "category": "Bugs & Logic",
                                                    "severity": "High",
                                                    "line": 1,
                                                    "issue": "The name is undefined.",
                                                    "fix": "Use the defined name.",
                                                }
                                            ],
                                            "corrected_code": "print('fixed')",
                                        }
                                    )
                                }
                            ]
                        }
                    }
                ]
            }
        ).encode()

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self):
                return response_body

        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            with patch("web_app.urllib.request.urlopen", return_value=FakeResponse()) as urlopen:
                result = generate_correction(
                    {
                        "source": "print(fxed)",
                        "findings": [
                            {
                                "category": "Bugs & Logic",
                                "severity": "Medium",
                                "line": 1,
                                "issue": "`fxed` is undefined.",
                                "fix": "Define or correct the name.",
                            }
                        ],
                        "syntax_error": None,
                    }
                )

        self.assertEqual(len(result["findings"]), 1)
        self.assertEqual(result["findings"][0]["category"], "Bugs & Logic")
        self.assertEqual(result["corrected_code"], "print('fixed')")
        self.assertIsNone(result["syntax_error"])
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("X-goog-api-key"), "test-key")
        self.assertNotIn("test-key", request.full_url)
        request_payload = json.loads(request.data)
        self.assertIn("systemInstruction", request_payload)
        system_instruction = request_payload["systemInstruction"]["parts"][0]["text"]
        self.assertIn("verifying that each heuristic finding is real", system_instruction)
        self.assertIn("additional actionable problems", system_instruction)
        self.assertEqual(
            request_payload["generationConfig"]["responseMimeType"],
            "application/json",
        )
        self.assertEqual(
            request_payload["generationConfig"]["responseSchema"]["required"],
            ["findings", "corrected_code"],
        )
        correction_prompt = request_payload["contents"][0]["parts"][0]["text"]
        self.assertIn("print(fxed)", correction_prompt)
        self.assertIn("`fxed` is undefined.", correction_prompt)

    def test_gemini_correction_rejects_findings_with_invalid_lines(self) -> None:
        response_body = json.dumps(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "findings": [
                                                {
                                                    "category": "Bugs & Logic",
                                                    "severity": "High",
                                                    "line": 2,
                                                    "issue": "Invalid line.",
                                                    "fix": "Fix it.",
                                                }
                                            ],
                                            "corrected_code": "print('fixed')",
                                        }
                                    )
                                }
                            ]
                        }
                    }
                ]
            }
        ).encode()

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self):
                return response_body

        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            with patch("web_app.urllib.request.urlopen", return_value=FakeResponse()):
                with self.assertRaisesRegex(GeminiUpstreamError, "invalid line number"):
                    generate_correction(
                        {
                            "source": "print('source has one line')",
                            "findings": [],
                            "syntax_error": None,
                        }
                    )

    def test_gemini_correction_rejects_truncated_output(self) -> None:
        response_body = json.dumps(
            {
                "candidates": [
                    {
                        "finishReason": "MAX_TOKENS",
                        "content": {"parts": [{"text": "print('incomplete"}]},
                    }
                ]
            }
        ).encode()

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self):
                return response_body

        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            with patch("web_app.urllib.request.urlopen", return_value=FakeResponse()):
                with self.assertRaisesRegex(GeminiUpstreamError, "may be incomplete"):
                    generate_correction(
                        {"source": "print('example')", "findings": [], "syntax_error": None}
                    )

    def test_gemini_correction_requires_server_api_key(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(GeminiConfigurationError, "GEMINI_API_KEY"):
                generate_correction({"source": "print('hello')"})

    def test_gemini_correction_rejects_invalid_and_oversized_source(self) -> None:
        with self.assertRaisesRegex(ValueError, "source code as a string"):
            generate_correction({"source": None})
        with self.assertRaisesRegex(ValueError, "100,000 characters or fewer"):
            generate_correction({"source": "x" * 100_001})


if __name__ == "__main__":
    unittest.main()
