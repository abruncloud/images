import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import mysql_discover
import release


class MySQLAutomationTests(unittest.TestCase):
    def fixture(self):
        return {"schema_version": 1, "gosu": {"version": "1.19"}, "go": {"version": "1.27.2", "base_image": "docker.io/library/golang:1.27.2-trixie@sha256:" + "e" * 64}, "releases": [{"major": line, "mysql_version": line + ".1", "variant": "oraclelinux9",
            "base_image": "docker.io/library/mysql:" + line + ".1-oraclelinux9@sha256:" + "a" * 64,
            "backup_base_image": "docker.io/library/oraclelinux:9-slim@sha256:" + "b" * 64,
            "platforms": ["linux/amd64", "linux/arm64"]} for line in ["8.4", "9.7"]]}

    def test_discovery_ignores_innovation_and_new_lts_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "images/mysql"
            image.mkdir(parents=True)
            (image / "image.json").write_text(json.dumps({"supported_majors": ["8.4", "9.7"], "variants": ["oraclelinux9"]}))
            (image / "versions.lock.json").write_text(json.dumps(self.fixture()))
            def resolve(tag, repository):
                return "docker.io/library/" + repository + ":" + tag + "@sha256:" + "c" * 64, ["linux/amd64", "linux/arm64"]
            def fetch(url):
                if url.endswith("/library/mysql"):
                    return ("\n\n".join("Tags: " + version + "-oraclelinux9\nGitCommit: " + "a" * 40 + "\nDirectory: " + line + "\nFile: Dockerfile.oracle" for line, version in [("8.4", "8.4.11"), ("9.7", "9.7.2"), ("9.8", "9.8.1")])).encode(), {}
                return ("ENV MYSQL_VERSION " + ("8.4.11" if "/8.4/" in url else "9.7.2") + "-1.el9\n").encode(), {}
            with patch.object(mysql_discover, "ROOT", root), patch.object(mysql_discover, "fetch", side_effect=fetch), patch.object(mysql_discover, "resolve", side_effect=resolve), patch.object(mysql_discover, "discover_hardening", return_value=(self.fixture()["gosu"], self.fixture()["go"])):
                lock = mysql_discover.discover()
            self.assertEqual([item["mysql_version"] for item in lock["releases"]], ["8.4.11", "9.7.2"])

    def test_review_inputs_allow_only_patches_and_pinned_base_rebuilds(self):
        before = self.fixture()
        after = copy.deepcopy(before)
        after["releases"][0]["mysql_version"] = "8.4.11"
        after["releases"][0]["base_image"] = "docker.io/library/mysql:8.4.11-oraclelinux9@sha256:" + "c" * 64
        after["releases"][0]["backup_base_image"] = "docker.io/library/oraclelinux:9-slim@sha256:" + "d" * 64
        self.assertEqual(mysql_discover.review_inputs(before), mysql_discover.review_inputs(after))
        after["new_dependency"] = {"version": "1"}
        self.assertNotEqual(mysql_discover.review_inputs(before), mysql_discover.review_inputs(after))
        after["releases"][0]["mysql_version"] = "9.0.1"
        with self.assertRaisesRegex(ValueError, "reviewed release line"):
            mysql_discover.review_inputs(after)

    def test_matrix_and_aliases_cover_both_native_architectures(self):
        entries = release.matrix(image="mysql")["include"]
        self.assertEqual({(item["major"], item["arch"]) for item in entries}, {(line, arch) for line in ["8.4"] for arch in ["amd64", "arm64"]})
        self.assertTrue(all(item["backup"] and item["directory"].startswith("images/mysql/generated/") for item in entries))
        for entry in entries:
            version = entry["mysql_version"]
            for target in ["backup"]:
                suffix = "-backup" if target == "backup" else ""
                self.assertEqual(set(release.tags(entry["major"], entry["variant"], target, "mysql")), {"abruncloud/mysql:" + value + suffix for value in [version, entry["major"], version + "-oraclelinux9", entry["major"] + "-oraclelinux9"]})

    def test_shared_required_check_covers_both_products(self):
        workflow = (release.ROOT / ".github/workflows/check.yml").read_text()
        self.assertIn("needs: [metadata, native-test, mysql-native-test, redis-native-test]", workflow)
        self.assertIn('test "$MYSQL_TESTS" = success', workflow)

    def test_discovery_is_exact_head_protected_and_explicitly_dispatched(self):
        workflow = (release.ROOT / ".github/workflows/mysql-discover.yml").read_text()
        for expected in ["branches/main", "grep -Fxq required", "--match-head-commit", "gh workflow run check.yml", "gh run watch", "gh workflow run mysql-release.yml", "automation/mysql-updates"]:
            self.assertIn(expected, workflow)
        self.assertNotIn("--admin", workflow)
        self.assertNotIn("/protection", workflow)

    def test_mysql_workflows_build_test_and_promote_only_backup(self):
        workflow = (release.ROOT / ".github/workflows/mysql-release.yml").read_text()
        self.assertNotIn("steps.runtime", workflow)
        self.assertNotIn("Scan runtime", workflow)
        self.assertIn("file: ${{ matrix.directory }}/Dockerfile.backup", workflow)
        self.assertIn("RUNTIME: ${{ matrix.base_image }}", workflow)
        self.assertIn("scan-backup.json", workflow)
        self.assertEqual(release.load("mysql")[0]["targets"], ["backup"])
        self.assertEqual(release.load("mysql")[0]["supported_majors"], ["8.4"])
