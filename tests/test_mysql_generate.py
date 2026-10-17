import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("mysql_generate", ROOT / "tools/mysql_generate.py")
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


class MySQLGeneratorTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.image = self.root / "images/mysql"
        (self.image / "templates").mkdir(parents=True)
        self.lock = json.loads((ROOT / "images/mysql/versions.lock.json").read_text())
        self.metadata = json.loads((ROOT / "images/mysql/image.json").read_text())
        for name in ("Dockerfile.gosu", "Dockerfile.oraclelinux9"):
            (self.image / "templates" / name).write_text((ROOT / "images/mysql/templates" / name).read_text())
        (self.image / "templates/Dockerfile.backup.oraclelinux9").write_text("FROM {{BACKUP_BASE_IMAGE}}\n# {{MYSQL_CLIENT_RPM_VERSION}}\n")

    def render(self):
        (self.image / "versions.lock.json").write_text(json.dumps(self.lock))
        (self.image / "image.json").write_text(json.dumps(self.metadata))
        with patch.object(generator, "ROOT", self.root), patch.object(generator, "IMAGE", self.image):
            return dict(generator.rendered_files())

    def test_renders_retained_runtime_and_backup_for_supported_line(self):
        files = self.render()
        self.assertEqual(len(files), 2)
        for recipe in files.values():
            self.assertNotIn("{{", recipe)
        self.assertIn(self.image / "generated/8.4/oraclelinux9/Dockerfile", files)
        self.assertIn(self.image / "generated/8.4/oraclelinux9/Dockerfile.backup", files)

    def test_rejects_cross_line(self):
        self.lock["releases"][0]["mysql_version"] = "9.7.2"
        with self.assertRaisesRegex(ValueError, "release line"):
            self.render()

    def test_rejects_unpinned_or_mismatched_base(self):
        for value in ("mysql:8.4", "docker.io/library/mysql:8.4.11-alpine@sha256:" + "0" * 64):
            with self.subTest(value=value):
                self.lock["releases"][0]["base_image"] = value
                with self.assertRaisesRegex(ValueError, "exact official"):
                    self.render()

    def test_rejects_missing_line_and_duplicate(self):
        original = copy.deepcopy(self.lock)
        self.lock["releases"].pop()
        with self.assertRaisesRegex(ValueError, "every supported"):
            self.render()
        self.lock = original
        self.lock["releases"].append(copy.deepcopy(self.lock["releases"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.render()

    def test_rejects_wrong_client_rpm(self):
        self.lock["releases"][0]["mysql_client_rpm_version"] = "8.4.10-1.el9"
        with self.assertRaisesRegex(ValueError, "client RPM"):
            self.render()

    def test_rejects_wrong_clean_distribution(self):
        self.lock["releases"][0]["backup_base_image"] = "docker.io/library/alpine:3.24@sha256:" + "0" * 64
        with self.assertRaisesRegex(ValueError, "Oracle Linux"):
            self.render()

    def test_rejects_gosu_checksum_and_compiler_mismatch(self):
        original = copy.deepcopy(self.lock)
        self.lock["gosu"]["sha256"] = "bad"
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.render()
        self.lock = original
        self.lock["go"]["version"] = "1.26.1"
        with self.assertRaisesRegex(ValueError, "pinned official"):
            self.render()

    def test_rejects_unresolved_template(self):
        (self.image / "templates/Dockerfile.oraclelinux9").write_text("FROM {{UNKNOWN}}")
        with self.assertRaisesRegex(ValueError, "unresolved"):
            self.render()


if __name__ == "__main__":
    unittest.main()
