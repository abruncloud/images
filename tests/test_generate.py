"""Guard reproducible generation and the reviewed input boundary."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / "tools" / "generate.py"
SPEC = importlib.util.spec_from_file_location("generate", MODULE)
generate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generate)


class GenerationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.image = self.root / "images/postgres"
        (self.image / "templates").mkdir(parents=True)
        self.metadata = {"supported_majors": ["18"], "variants": ["trixie"], "platforms": ["linux/amd64", "linux/arm64"]}
        self.lock = {"schema_version": 1, "pgvector": {"version": "0.8.7", "url": "https://github.com/pgvector/pgvector/archive/refs/tags/v0.8.7.tar.gz", "sha256": "a" * 64}, "releases": [{"postgres_version": "18.6", "major": "18", "variant": "trixie", "base_image": "postgres:18.6-trixie@sha256:" + "b" * 64, "platforms": ["linux/amd64", "linux/arm64"]}]}
        for name in ("Dockerfile.debian", "Dockerfile.alpine", "Dockerfile.backup.debian", "Dockerfile.backup.alpine"):
            (self.image / "templates" / name).write_text("FROM {{BASE_IMAGE}}\n# vector={{PGVECTOR_VERSION}}\n")
        for name, value in (("ROOT", self.root), ("IMAGE", self.image)):
            mock = patch.object(generate, name, value)
            mock.start()
            self.addCleanup(mock.stop)

    def write_inputs(self):
        (self.image / "image.json").write_text(json.dumps(self.metadata))
        (self.image / "versions.lock.json").write_text(json.dumps(self.lock))

    def render(self):
        self.write_inputs()
        return dict(generate.rendered_files())

    def test_resolves_distro_and_both_recipes(self):
        self.metadata["variants"].append("alpine3.24")
        self.lock["releases"].append(dict(self.lock["releases"][0], variant="alpine3.24", base_image="postgres:18.6-alpine3.24@sha256:" + "c" * 64))
        files = self.render()
        self.assertEqual(len(files), 4)
        self.assertIn(self.image / "generated/18/alpine3.24/Dockerfile.backup", files)
        self.assertTrue(all("{{" not in text for text in files.values()))

    def test_rejects_unpinned_source(self):
        self.lock["releases"][0]["base_image"] = "postgres:18"
        with self.assertRaisesRegex(ValueError, "digest"):
            self.render()

    def test_rejects_mismatched_major(self):
        self.lock["releases"][0]["postgres_version"] = "17.9"
        with self.assertRaisesRegex(ValueError, "disagree"):
            self.render()

    def test_rejects_unverified_archive(self):
        self.lock["pgvector"]["sha256"] = "wrong"
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.render()

    def test_rejects_wrong_base_distribution(self):
        self.lock["releases"][0]["base_image"] = "postgres:18.6-alpine3.24@sha256:" + "b" * 64
        with self.assertRaisesRegex(ValueError, "distribution"):
            self.render()

    def test_rejects_missing_supported_distribution(self):
        self.metadata["variants"].append("alpine3.24")
        with self.assertRaisesRegex(ValueError, "every supported"):
            self.render()

    def test_rejects_unknown_template_token(self):
        (self.image / "templates/Dockerfile.debian").write_text("FROM {{UNKNOWN}}\n")
        with self.assertRaisesRegex(ValueError, "token"):
            self.render()

    def test_check_detects_drift_and_stale_recipe(self):
        self.write_inputs()
        with patch("sys.argv", ["generate.py"]):
            self.assertEqual(generate.main(), 0)
        with patch("sys.argv", ["generate.py", "--check"]):
            self.assertEqual(generate.main(), 0)
        stale = self.image / "generated/17/trixie/Dockerfile"
        stale.parent.mkdir(parents=True)
        stale.write_text("stale\n")
        with patch("sys.argv", ["generate.py", "--check"]):
            self.assertEqual(generate.main(), 1)
        with patch("sys.argv", ["generate.py"]):
            self.assertEqual(generate.main(), 0)
        self.assertFalse(stale.exists())


if __name__ == "__main__":
    unittest.main()
