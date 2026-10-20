import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.openrouter_repair import (
    _apply_failure_context,
    _canonicalize_bare_diff_headers,
    _prompt,
)
from scripts.repair_patch_policy import (
    PatchRejected,
    _safe_apply_diagnostic,
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

    def test_prompt_requires_matching_git_diff_headers(self):
        prompt = _prompt("source", "failure", None)
        self.assertIn("diff --git a/path b/path", prompt)
        self.assertIn("--- a/path", prompt)
        self.assertIn("+++ b/path", prompt)

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
