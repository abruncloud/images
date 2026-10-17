import copy
import json
from pathlib import Path
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import redis_discover
import release
class RedisAutomationTests(unittest.TestCase):
    def test_only_backup_targets_and_native_architectures(self):
        entries = release.matrix("backup", "redis")["include"]
        self.assertEqual({entry["arch"] for entry in entries}, {"amd64", "arm64"})
        self.assertTrue(all(entry["backup"] for entry in entries))
        self.assertEqual(release.matrix("runtime", "redis")["include"], [])
    def test_only_real_backup_tags(self):
        self.assertEqual(set(release.tags("8.2", "alpine3.22", "backup", "redis")), {"abruncloud/redis:8.2.10-alpine3.22-backup", "abruncloud/redis:8.2-alpine3.22-backup", "abruncloud/redis:8.2.10-backup", "abruncloud/redis:8.2-backup"})
    def test_patch_inputs_routine_but_distribution_and_line_not(self):
        lock = json.loads((ROOT / "images/redis/versions.lock.json").read_text())
        updated = copy.deepcopy(lock)
        record = updated["releases"][0]
        record.update(redis_version="8.2.11", source_url="https://github.com/redis/redis/archive/refs/tags/8.2.11.tar.gz", source_sha256="b"*64, base_image="docker.io/library/redis:8.2.11-bookworm@sha256:"+"c"*64, official_source_commit="d"*40)
        self.assertEqual(redis_discover.review_inputs(lock), redis_discover.review_inputs(updated))
        record["backup_base_image"] = "alpine:latest"
        with self.assertRaises(ValueError): redis_discover.review_inputs(updated)
    def test_release_scans_every_architecture_and_no_public_staging_tags(self):
        workflow = (ROOT / ".github/workflows/redis-release.yml").read_text()
        self.assertIn("tools/security_gate.py --policy images/redis/security-policy.json scan-backup.json", workflow)
        self.assertIn("ghcr.io/abruncloud/redis-ci:build-", workflow)
        self.assertNotIn("abruncloud/redis:build-", workflow)
        self.assertIn("sbom: true", workflow)
        self.assertIn("provenance: mode=max", workflow)
        self.assertIn("tests/run-redis-backup.sh", workflow)
    def test_existing_required_ci_includes_redis(self):
        workflow = (ROOT / ".github/workflows/check.yml").read_text()
        self.assertIn("needs: [metadata, native-test, mysql-native-test, redis-native-test]", workflow)
        self.assertIn('test "$REDIS_TESTS" = success', workflow)

    def test_native_scan_identity_is_explicit(self):
        for name in ["release", "rescan"]:
            workflow = (ROOT / f".github/workflows/redis-{name}.yml").read_text()
            self.assertIn("TRIVY_PLATFORM: linux/${{ matrix.arch }}", workflow)
            self.assertIn('report.get("Metadata", {}).get("ImageConfig", {}).get("architecture")', workflow)
    def test_update_merging_requires_actual_pr_event_and_manual_exercise_never_merges(self):
        workflow = (ROOT / ".github/workflows/redis-discover.yml").read_text()
        self.assertIn("--event pull_request", workflow)
        self.assertNotIn("gh workflow run check.yml", workflow)
        self.assertIn("qualify_update_flow", workflow)
        self.assertIn("approval_required", workflow)
        self.assertIn('&& [ "${{ inputs.qualify_update_flow }}" != true ]', workflow)
