import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import discover
import release
import publish

class AutomationTests(unittest.TestCase):
    def test_aliases_no_latest_and_backup_suffix(self):
        metadata, lock = release.load()
        for item in lock["releases"]:
            runtime = release.tags(item["major"], item["variant"], "runtime")
            backup = release.tags(item["major"], item["variant"], "backup")
            self.assertEqual(backup, [tag + "-backup" for tag in runtime])
            self.assertIn("abruncloud/postgres:" + item["postgres_version"] + "-" + item["variant"], runtime)
            self.assertFalse(any("latest" in tag for tag in runtime))
            if item["variant"] == metadata["default_variant"]:
                self.assertIn("abruncloud/postgres:" + item["major"], runtime)
            if item["variant"] == metadata["default_alpine_variant"]:
                self.assertIn("abruncloud/postgres:" + item["major"] + "-alpine", runtime)

    def test_native_matrix_covers_every_variant(self):
        metadata, lock = release.load()
        entries = release.matrix()["include"]
        self.assertEqual({(entry["major"], entry["variant"], entry["arch"]) for entry in entries}, {
            (item["major"], item["variant"], arch) for item in lock["releases"] for arch in ["amd64", "arm64"]})
        self.assertTrue(all(entry["runner"].endswith("-arm") == (entry["arch"] == "arm64") for entry in entries))

    def test_registry_requires_both_architectures(self):
        raw = json.dumps({"manifests": [{"platform": {"os": "linux", "architecture": "amd64"}}]}).encode()
        import hashlib
        with patch.object(discover, "fetch", side_effect=[(b'{"token":"token"}', {}),
                (raw, {"Docker-Content-Digest": "sha256:" + hashlib.sha256(raw).hexdigest()})]):
            with self.assertRaisesRegex(ValueError, "native platforms"):
                discover.resolve("18.6-trixie")

    def test_registry_digest_is_verified(self):
        with patch.object(discover, "fetch", side_effect=[(b'{"token":"token"}', {}),
                (b'{}', {"Docker-Content-Digest": "sha256:" + "0" * 64})]):
            with self.assertRaisesRegex(ValueError, "digest verification"):
                discover.resolve("18.6-trixie")

    def test_stale_publication_never_calls_docker(self):
        with patch.dict("os.environ", {"EXPECTED_SHA": "a" * 40}), patch.object(publish, "current_main", return_value="b" * 40), patch.object(publish, "command") as command:
            with self.assertRaisesRegex(SystemExit, "stale publication"):
                publish.main()
            command.assert_not_called()

if __name__ == "__main__":
    unittest.main()
