import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import publish

class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.previous = Path.cwd()
        os.chdir(self.temp.name)
        self.addCleanup(os.chdir, self.previous)
        Path("digests").mkdir()
        for target in ["runtime", "backup"]:
            for arch in ["amd64", "arm64"]:
                Path("digests", f"18-trixie-{target}-{arch}").write_text("sha256:" + "a" * 64)
        self.env = {"EXPECTED_SHA": "b" * 40, "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "2"}
        self.lock = {"schema_version": 1, "pgvector": {"version": "test"}, "releases": [{"major": "18", "variant": "trixie"}]}
        self.calls = []

    def command(self, *args):
        self.calls.append(args)
        if "inspect" in args:
            return json.dumps({"digest": "sha256:" + "c" * 64})
        return ""

    def execute(self, main_refs=None, command=None):
        with patch.dict(os.environ, self.env), patch.object(publish, "current_main", side_effect=main_refs or ["b" * 40, "b" * 40]), patch.object(publish, "load", return_value=({}, self.lock)), patch.object(publish, "tags", side_effect=lambda major, variant, target: ["abruncloud/postgres:18" + ("-backup" if target == "backup" else "")]), patch.object(publish, "command", side_effect=command or self.command):
            publish.main()

    def test_release_records_build_identity_inputs_and_exact_digests(self):
        self.execute()
        record = json.loads(Path("release.json").read_text())
        self.assertEqual(record["source_commit"], self.env["EXPECTED_SHA"])
        self.assertEqual(record["build_id"], self.env["EXPECTED_SHA"] + "-123-2")
        self.assertEqual(record["workflow_run_id"], "123")
        self.assertEqual(record["workflow_run_attempt"], "2")
        self.assertEqual(record["inputs"], self.lock)
        self.assertEqual({item["target"] for item in record["images"]}, {"runtime", "backup"})
        self.assertTrue(all(item["digest"] == "sha256:" + "c" * 64 for item in record["images"]))
        self.assertTrue(all(len(item["native_refs"]) == 2 for item in record["images"]))
        signs = [index for index, call in enumerate(self.calls) if call[:2] == ("cosign", "sign")]
        promotions = [index for index, call in enumerate(self.calls) if "--prefer-index=false" in call]
        self.assertEqual(len(signs), 6)
        self.assertGreater(min(promotions), max(signs))

    def test_main_advancing_before_promotion_blocks_all_aliases(self):
        with self.assertRaisesRegex(SystemExit, "main advanced during signing"):
            self.execute(main_refs=["b" * 40, "d" * 40])
        self.assertFalse(any("--prefer-index=false" in call for call in self.calls))
        self.assertFalse(Path("release.json").exists())

    def test_missing_architecture_prevents_promotion(self):
        Path("digests/18-trixie-runtime-arm64").unlink()
        with self.assertRaises(FileNotFoundError):
            self.execute()
        self.assertFalse(any("--prefer-index=false" in call for call in self.calls))

    def test_invalid_multiplatform_digest_prevents_promotion(self):
        def invalid(*args):
            self.calls.append(args)
            return json.dumps({"digest": "not-a-digest"}) if "inspect" in args else ""
        with self.assertRaisesRegex(ValueError, "multi-platform digest"):
            self.execute(command=invalid)
        self.assertFalse(any("--prefer-index=false" in call for call in self.calls))

    def test_invalid_run_identity_prevents_any_registry_command(self):
        self.env["GITHUB_RUN_ID"] = "unsafe/value"
        with self.assertRaisesRegex(ValueError, "workflow run identity"):
            self.execute()
        self.assertEqual(self.calls, [])
