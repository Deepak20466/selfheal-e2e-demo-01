import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.openrouter_repair import _canonicalize_bare_diff_headers, _prompt
from scripts.repair_patch_policy import PatchRejected, validate_patch


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


if __name__ == "__main__":
    unittest.main()