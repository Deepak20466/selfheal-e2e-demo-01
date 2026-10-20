import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.openrouter_repair import (
    _collect_source,
    _completion_with_correction,
    _parse_repair_response,
    _apply_failure_context,
    _canonicalize_bare_diff_headers,
    _prompt,
)
from scripts.repair_providers import (
    REPAIR_JSON_SCHEMA,
    ProviderCompletion,
    _without_additional_properties,
)
from scripts.repair_patch_policy import (
    PatchRejected,
    _safe_apply_diagnostic,
    build_exact_replacement_patch,
    validate_patch,
)


PATCH = (
    b"diff --git a/apps/calculator.py b/apps/calculator.py\n"
    b"index 1111111..2222222 100644\n"
    b"--- apps/calculator.py\n"
    b"+++ apps/calculator.py\n"
    b"@@ -1 +1 @@\n"
    b"-return left - right\n"
    b"+return left + right\n"
)


class RepairPatchHeaderTests(unittest.TestCase):
    def test_matching_bare_headers_are_normalized_to_exact_git_paths(self):
        normalized = _canonicalize_bare_diff_headers(PATCH)
        self.assertIn(b"--- a/apps/calculator.py\n", normalized)
        self.assertIn(b"+++ b/apps/calculator.py\n", normalized)

    def test_mismatched_header_is_not_normalized_or_accepted(self):
        malformed = PATCH.replace(b"--- apps/calculator.py", b"--- another.py")
        normalized = _canonicalize_bare_diff_headers(malformed)
        self.assertIn(b"--- another.py\n", normalized)
        with TemporaryDirectory() as directory:
            repo = Path(directory)
            (repo / "apps").mkdir()
            (repo / "apps" / "calculator.py").write_text("return left - right\n", encoding="utf-8")
            with self.assertRaisesRegex(PatchRejected, "unsafe or unexpected old file header"):
                validate_patch(normalized, repo, check_apply=False)

    def test_prompt_requires_exact_text_patch_schema(self):
        prompt = _prompt("source", "failure", None)
        self.assertIn("object `patch`", prompt)
        self.assertIn("`path`, `old_text`, and `new_text`", prompt)
        self.assertIn("exact, unique substring", prompt)

    def test_gemini_schema_subset_keeps_fields_but_removes_nested_extras(self):
        gemini_schema = _without_additional_properties(REPAIR_JSON_SCHEMA)
        patch_schema = gemini_schema["properties"]["patch"]
        self.assertNotIn("additionalProperties", patch_schema)
        self.assertEqual(
            patch_schema["required"], ["path", "old_text", "new_text"]
        )

    def test_parser_rejects_extra_replacement_properties(self):
        response = json.dumps(
            {
                "diagnosis": "The addition causes the off-by-one result.",
                "patch": {
                    "path": "apps/calculator.py",
                    "old_text": "return left + right + 1",
                    "new_text": "return left + right",
                    "extra": "rejected",
                },
            }
        )
        with self.assertRaisesRegex(RuntimeError, "strict JSON schema"):
            _parse_repair_response(response)

    def test_exact_replacement_builds_a_patch_that_applies(self):
        with TemporaryDirectory() as directory:
            repo = Path(directory)
            (repo / "apps").mkdir()
            source = repo / "apps" / "calculator.py"
            source.write_bytes(
                b"def add_numbers(left, right):\n    return left + right + 1\n"
            )
            subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True)
            patch = build_exact_replacement_patch(
                repo,
                "apps/calculator.py",
                "    return left + right + 1\n",
                "    return left + right\n",
            )
            validate_patch(patch, repo)
            subprocess.run(["git", "apply"], cwd=repo, input=patch, check=True)
            self.assertEqual(
                source.read_text(encoding="utf-8"),
                "def add_numbers(left, right):\n    return left + right\n",
            )

    def test_nonunique_exact_replacement_is_rejected(self):
        with TemporaryDirectory() as directory:
            repo = Path(directory)
            (repo / "apps").mkdir()
            (repo / "apps" / "calculator.py").write_bytes(
                b"return left + right + 1\nreturn left + right + 1\n"
            )
            with self.assertRaisesRegex(PatchRejected, "match exactly once"):
                build_exact_replacement_patch(
                    repo,
                    "apps/calculator.py",
                    "return left + right + 1\n",
                    "return left + right\n",
                )

    def test_bounded_correction_uses_exact_selected_source(self):
        class StubProvider:
            name = "stub"

            def __init__(self):
                self.prompts = []
                self.responses = [
                    {
                        "diagnosis": "The extra one causes the failure.",
                        "patch": {
                            "path": "apps/calculator.py",
                            "old_text": "    return left + right + 2\n",
                            "new_text": "    return left + right\n",
                        },
                    },
                    {
                        "diagnosis": "The extra one causes the failure.",
                        "patch": {
                            "path": "apps/calculator.py",
                            "old_text": "    return left + right + 1\n",
                            "new_text": "    return left + right\n",
                        },
                    },
                ]

            def complete(self, prompt):
                self.prompts.append(prompt)
                response = json.dumps(self.responses.pop(0))
                return ProviderCompletion("stub", "test", response)

        with TemporaryDirectory() as directory:
            repo = Path(directory)
            (repo / "apps").mkdir()
            (repo / "apps" / "calculator.py").write_bytes(
                b"def add_numbers(left, right):\n    return left + right + 1\n"
            )
            subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True)
            source = _collect_source(repo)
            provider = StubProvider()
            _completion, _diagnosis, patch = _completion_with_correction(
                provider, repo, source, "Expected 42, got 43.", None
            )
            validate_patch(patch, repo)
        self.assertEqual(len(provider.prompts), 2)
        self.assertIn("Exact selected-commit source lines", provider.prompts[1])
        self.assertIn("2:     return left + right + 1", provider.prompts[1])

    def test_correction_prompt_treats_line_numbers_as_metadata(self):
        prompt = _prompt(
            "source",
            "failure",
            "previous patch",
            correction_reason=(
                "Use these exact lines: <selected_source_context>\n"
                "12: return left + right + 1\n</selected_source_context>"
            ),
        )
        self.assertIn("line-number labels are metadata only", prompt)
        self.assertIn("omit them and copy", prompt)
        self.assertIn("source text after each label exactly", prompt)

    def test_unknown_apply_error_identifies_only_the_validated_single_target(self):
        from pathlib import PurePosixPath

        with TemporaryDirectory() as directory:
            repo = Path(directory)
            diagnostic = _safe_apply_diagnostic(
                b"error: patch fragment without header at line 4\n",
                [PurePosixPath("apps/calculator.py")],
                repo,
            )
        self.assertEqual(
            diagnostic,
            "git apply --check rejected apps/calculator.py at an unspecified line",
        )

    def test_unknown_apply_line_adds_exact_small_file_context_to_correction(self):
        with TemporaryDirectory() as directory:
            repo = Path(directory)
            (repo / "apps").mkdir()
            (repo / "apps" / "calculator.py").write_text(
                "def add(left, right):\n    return left + right + 1\n",
                encoding="utf-8",
            )
            context = _apply_failure_context(
                "patch does not apply cleanly to the selected commit; "
                "git apply --check rejected apps/calculator.py at an unspecified line",
                repo,
            )
        self.assertIn("Exact selected-commit source lines 1-2", context)
        self.assertIn("1: def add(left, right):", context)
        self.assertIn("2:     return left + right + 1", context)


if __name__ == "__main__":
    unittest.main()
