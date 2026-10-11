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
                Path("digests", f"18-alpine3.24-{target}-{arch}").write_text("sha256:" + "a" * 64)
        self.env = {"EXPECTED_SHA": "b" * 40, "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "2"}
        self.lock = {"schema_version": 1, "pgvector": {"version": "test"}, "releases": [{"major": "18", "variant": "alpine3.24"}]}
        self.calls = []

    def command(self, *args):
        self.calls.append(args)
        if args[:2] == ("crane", "digest"):
            return args[-1].rsplit("@", 1)[1]
        if "inspect" in args:
            return json.dumps({"digest": "sha256:" + "c" * 64})
        return ""

    def execute(self, main_refs=None, command=None, target="all"):
        with patch.dict(os.environ, self.env), patch.object(publish, "current_main", side_effect=main_refs or ["b" * 40, "b" * 40]), patch.object(publish, "load", return_value=({"backup_variant": "alpine3.24"}, self.lock)), patch.object(publish, "tags", side_effect=lambda major, variant, target: ["abruncloud/postgres:18" + ("-backup" if target == "backup" else "")]), patch.object(publish, "command", side_effect=command or self.command):
            publish.main(target)

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
        self.assertEqual(record["candidate_repository"], "ghcr.io/abruncloud/postgres-ci")
        self.assertTrue(all(item["candidate_ref"].startswith("ghcr.io/abruncloud/postgres-ci@sha256:") for item in record["images"]))
        self.assertTrue(all(all(ref.startswith("abruncloud/postgres@sha256:") for ref in item["native_refs"]) for item in record["images"]))
        signs = [index for index, call in enumerate(self.calls) if call[:2] == ("cosign", "sign")]
        promotions = [index for index, call in enumerate(self.calls) if "--prefer-index=false" in call]
        self.assertEqual(len(signs), 6)
        self.assertGreater(min(promotions), max(signs))

    def test_runtime_only_variant_does_not_publish_backup(self):
        self.lock["releases"][0]["variant"] = "trixie"
        for arch in ["amd64", "arm64"]:
            Path("digests", f"18-trixie-runtime-{arch}").write_text("sha256:" + "a" * 64)
        self.execute()
        record = json.loads(Path("release.json").read_text())
        self.assertEqual([item["target"] for item in record["images"]], ["runtime"])
        self.assertFalse(any("backup" in argument for call in self.calls for argument in call))

    def test_main_advancing_before_promotion_blocks_all_aliases(self):
        with self.assertRaisesRegex(SystemExit, "main advanced during signing"):
            self.execute(main_refs=["b" * 40, "d" * 40])
        self.assertFalse(any("--prefer-index=false" in call for call in self.calls))
        self.assertFalse(Path("release.json").exists())

    def test_missing_architecture_prevents_promotion(self):
        Path("digests/18-alpine3.24-runtime-arm64").unlink()
        with self.assertRaises(FileNotFoundError):
            self.execute()
        self.assertFalse(any("--prefer-index=false" in call for call in self.calls))

    def test_invalid_multiplatform_digest_prevents_promotion(self):
        def invalid(*args):
            self.calls.append(args)
            if args[:2] == ("crane", "digest"):
                return args[-1].rsplit("@", 1)[1]
            return json.dumps({"digest": "not-a-digest"}) if "inspect" in args else ""
        with self.assertRaisesRegex(ValueError, "multi-platform digest"):
            self.execute(command=invalid)
        self.assertFalse(any("--prefer-index=false" in call for call in self.calls))

    def test_invalid_run_identity_prevents_any_registry_command(self):
        self.env["GITHUB_RUN_ID"] = "unsafe/value"
        with self.assertRaisesRegex(ValueError, "workflow run identity"):
            self.execute()
        self.assertEqual(self.calls, [])

    def test_candidate_tags_only_exist_in_ghcr(self):
        self.execute()
        tagged = [call[call.index("--tag") + 1] for call in self.calls if "--tag" in call]
        archives = [reference for reference in tagged if ":build-" in reference]
        self.assertEqual(len(archives), 2)
        self.assertTrue(all(reference.startswith("ghcr.io/abruncloud/postgres-ci:build-") for reference in archives))
        public = [reference for reference in tagged if reference.startswith("abruncloud/postgres:")]
        self.assertEqual(public, ["abruncloud/postgres:18", "abruncloud/postgres:18-backup"])

    def test_copy_and_verify_all_native_and_combined_digests_before_aliases(self):
        self.execute()
        copies = [(index, call) for index, call in enumerate(self.calls) if call[:2] == ("crane", "copy")]
        self.assertEqual(len(copies), 6)
        for _, call in copies:
            self.assertTrue(call[2].startswith("ghcr.io/abruncloud/postgres-ci@sha256:"))
            self.assertTrue(call[3].startswith("abruncloud/postgres@sha256:"))
            self.assertEqual(call[2].rsplit("@", 1)[1], call[3].rsplit("@", 1)[1])
        first_alias = next(index for index, call in enumerate(self.calls) if "--prefer-index=false" in call)
        self.assertGreater(first_alias, max(index for index, _ in copies))
        signs = [call for call in self.calls if call[:2] == ("cosign", "sign")]
        self.assertTrue(all(call[-1].startswith("abruncloud/postgres@sha256:") for call in signs))
        self.assertEqual(sum(call[:2] == ("crane", "digest") for call in self.calls), 6)

    def test_copy_digest_mismatch_prevents_signing_and_alias_promotion(self):
        def mismatch(*args):
            self.calls.append(args)
            return "sha256:" + "d" * 64 if args[:2] == ("crane", "digest") else ""
        with self.assertRaisesRegex(ValueError, "digest changed"):
            self.execute(command=mismatch)
        self.assertFalse(any(call[:2] == ("cosign", "sign") for call in self.calls))
        self.assertFalse(any("--prefer-index=false" in call for call in self.calls))

    def test_cross_registry_copy_failure_never_moves_public_aliases(self):
        import subprocess
        def failure(*args):
            self.calls.append(args)
            if args[:2] == ("crane", "copy"):
                raise subprocess.CalledProcessError(1, args)
            return ""
        with self.assertRaises(subprocess.CalledProcessError):
            self.execute(command=failure)
        self.assertFalse(any("--prefer-index=false" in call for call in self.calls))

    def test_backup_only_ignores_runtime_digests_and_aliases(self):
        for path in Path("digests").glob("*runtime*"):
            path.unlink()
        self.execute(target="backup")
        record = json.loads(Path("release.json").read_text())
        self.assertEqual(record["publication_target"], "backup")
        self.assertEqual([item["target"] for item in record["images"]], ["backup"])
        public = [call[call.index("--tag") + 1] for call in self.calls if "--tag" in call and call[call.index("--tag") + 1].startswith("abruncloud/postgres:")]
        self.assertEqual(public, ["abruncloud/postgres:18-backup"])
        self.assertEqual(sum(call[:2] == ("cosign", "sign") for call in self.calls), 3)

    def test_backup_only_stale_publication_still_blocks_aliases(self):
        with self.assertRaisesRegex(SystemExit, "main advanced during signing"):
            self.execute(main_refs=["b" * 40, "d" * 40], target="backup")
        self.assertFalse(any("--prefer-index=false" in call for call in self.calls))

    def test_unknown_publication_target_fails_before_registry_calls(self):
        with self.assertRaisesRegex(ValueError, "Unsupported publication target"):
            self.execute(target="unknown")
        self.assertEqual(self.calls, [])
