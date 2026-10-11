import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import security_gate

class SecurityGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def report(self, name, vulnerabilities):
        path = self.root / name
        path.write_text(json.dumps({"SchemaVersion": 2, "ArtifactType": "container_image", "ArtifactName": "test@sha256:abc",
                                   "Results": [{"Vulnerabilities": vulnerabilities}]}))
        return path

    def test_clean_and_lower_severities_pass(self):
        paths = [self.report("runtime.json", None), self.report("backup.json", [{"Severity": "MEDIUM"}])]
        self.assertTrue(security_gate.evaluate(paths)[0])

    def test_unfixed_high_blocks(self):
        path = self.report("runtime.json", [{"Severity": "HIGH", "FixedVersion": ""}])
        self.assertFalse(security_gate.evaluate([path])[0])

    def test_critical_in_backup_blocks_even_clean_runtime(self):
        paths = [self.report("runtime.json", []), self.report("backup.json", [{"Severity": "CRITICAL"}])]
        passed, lines = security_gate.evaluate(paths)
        self.assertFalse(passed)
        self.assertEqual(len(lines), 2)
        self.assertIn("CRITICAL=1", lines[1])

    def test_missing_report_blocks_and_still_evaluates_other(self):
        paths = [self.root / "absent.json", self.report("backup.json", [{"Severity": "HIGH"}])]
        passed, lines = security_gate.evaluate(paths)
        self.assertFalse(passed)
        self.assertEqual(len(lines), 2)
        self.assertIn("HIGH=1", lines[1])

    def test_malformed_json_blocks(self):
        path = self.root / "report.json"
        path.write_text("not json")
        self.assertFalse(security_gate.evaluate([path])[0])

    def test_incomplete_report_blocks(self):
        path = self.root / "report.json"
        path.write_text(json.dumps({"SchemaVersion": 2, "ArtifactType": "container_image", "ArtifactName": "test"}))
        self.assertFalse(security_gate.evaluate([path])[0])

    def test_invalid_severity_blocks(self):
        path = self.report("report.json", [{"Severity": "unrecognized"}])
        self.assertFalse(security_gate.evaluate([path])[0])

    def test_wrong_artifact_blocks(self):
        path = self.root / "report.json"
        path.write_text(json.dumps({"SchemaVersion": 2, "ArtifactType": "filesystem", "ArtifactName": "test", "Results": []}))
        self.assertFalse(security_gate.evaluate([path])[0])
