from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LEGACY_VM_TERM = "fire" + "cracker"
TEXT_SUFFIXES = {
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".py",
    ".sh",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
SKIP_DIRS = {
    ".git",
    ".pytest_cache",
    "__pycache__",
    "runs",
}


class RepositoryPackagingTests(unittest.TestCase):
    def test_repository_contains_no_legacy_vm_runtime_references(self) -> None:
        offenders: list[str] = []
        for path in PROJECT_ROOT.rglob("*"):
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            relative = path.relative_to(PROJECT_ROOT)
            if LEGACY_VM_TERM in str(relative).lower():
                offenders.append(str(relative))
                continue
            if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            content = path.read_text(encoding="utf-8", errors="ignore").lower()
            if LEGACY_VM_TERM in content:
                offenders.append(str(relative))

        self.assertEqual(offenders, [])

    def test_repository_has_direct_deployment_entrypoints(self) -> None:
        expected_files = [
            "Dockerfile",
            "docker-compose.yml",
            ".env.example",
            "docs/deployment.md",
            "bin/start_dashboard.sh",
            "bin/run_mini_swe_agent_team_v2_sweep_with_metrics.sh",
        ]

        missing = [relative for relative in expected_files if not (PROJECT_ROOT / relative).exists()]
        self.assertEqual(missing, [])

        compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn("dashboard", compose)
        self.assertIn("8080:8080", compose)
        self.assertIn("aab_framework.dashboard", dockerfile)


if __name__ == "__main__":
    unittest.main()
