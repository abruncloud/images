import fnmatch
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import release

class BackupPublicationTests(unittest.TestCase):
    def test_backup_matrix_qualifies_only_backup_distribution_both_architectures(self):
        metadata, _ = release.load()
        entries = release.matrix("backup")["include"]
        self.assertTrue(entries)
        self.assertEqual({entry["arch"] for entry in entries}, {"amd64", "arm64"})
        self.assertTrue(all(entry["backup"] and entry["variant"] == metadata["backup_variant"] for entry in entries))

    def test_backup_dispatch_keeps_native_recovery_scan_signing_and_head_guards(self):
        workflow = (ROOT / ".github/workflows/backup-release.yml").read_text()
        self.assertNotIn("\n  push:\n", workflow)
        for command in ["tools/release.py matrix --target backup", "tests/run-backup.sh", "scan-runtime.json scan-backup.json", "tools/publish.py --target backup", "cosign-installer", "retention-days: 90"]:
            self.assertIn(command, workflow)
        self.assertIn("group: postgres-publication", workflow)

    def test_backup_changes_do_not_trigger_full_server_publication(self):
        workflow = (ROOT / ".github/workflows/release.yml").read_text()
        paths = [line.strip()[2:] for line in workflow.splitlines() if line.startswith("      - ")]
        changed = ["images/postgres/templates/Dockerfile.backup.alpine", "images/postgres/generated/18/alpine3.24/Dockerfile.backup", "images/postgres/README.md", "tests/run-backup.sh", "tools/release.py", "tools/publish.py", ".github/workflows/backup-release.yml", ".github/workflows/release.yml"]
        self.assertFalse(any(fnmatch.fnmatch(path, pattern) for path in changed for pattern in paths))
        self.assertTrue(any(fnmatch.fnmatch("images/postgres/templates/Dockerfile.alpine", pattern) for pattern in paths))
        self.assertIn("workflow_dispatch:", workflow)
