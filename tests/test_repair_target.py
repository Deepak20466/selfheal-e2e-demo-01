import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.resolve_repair_target import resolve


class RepairTargetTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.allowlist = Path(self.temp_dir.name) / "allowlist.txt"
        self.allowlist.write_text("Deepak20466/selfheal-e2e-demo-01\n", encoding="utf-8")

    def _event(self, *, branch="trial/seed-ci-failure", pull_requests=None):
        return {
            "repository": {
                "full_name": "Deepak20466/selfheal-e2e-demo-01",
                "default_branch": "main",
                "private": False,
            },
            "workflow_run": {
                "id": 123,
                "name": "CI",
                "conclusion": "failure",
                "head_sha": "a" * 40,
                "head_branch": branch,
                "head_repository": {"full_name": "Deepak20466/selfheal-e2e-demo-01"},
                "pull_requests": pull_requests or [],
            },
        }

    def test_push_failure_uses_the_failed_seed_branch(self):
        result = resolve(self._event(), self.allowlist, "Deepak20466/selfheal-e2e-demo-01")
        self.assertEqual(result["base"], "trial/seed-ci-failure")
        self.assertEqual(result["sha"], "a" * 40)

    def test_pull_request_failure_uses_the_declared_base_branch(self):
        pull_requests = [
            {"head": {"sha": "b" * 40}, "base": {"ref": "main"}},
        ]
        result = resolve(
            self._event(pull_requests=pull_requests),
            self.allowlist,
            "Deepak20466/selfheal-e2e-demo-01",
        )
        self.assertEqual(result["base"], "main")
        self.assertEqual(result["sha"], "b" * 40)


if __name__ == "__main__":
    unittest.main()
