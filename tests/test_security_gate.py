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


class ActionablePolicyTests(unittest.TestCase):
    def setUp(self):
        from datetime import date
        self.today = date(2026, 10, 11)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.assessment = {"id": "CVE-2026-6653", "os_family": "debian", "os_major": "13", "pkg_name": "libxml2",
                           "installed_version": "2.12.7+dfsg+really2.9.14-2.1+deb13u3",
                           "assessment": "Debian trixie: no-dsa (Minor issue)",
                           "source": "https://security-tracker.debian.org/tracker/CVE-2026-6653",
                           "reason": "Vendor urgency assessment; accepted risk pending an upstream fix.",
                           "owner": "repository maintainers", "expires": "2026-11-10"}
        self.policy = {"schema_version": 1, "mode": "actionable", "critical_assessments": [self.assessment]}
        self.finding = {"Severity": "CRITICAL", "VulnerabilityID": self.assessment["id"],
                        "PkgName": "libxml2", "InstalledVersion": self.assessment["installed_version"], "FixedVersion": ""}

    def report(self, findings=None, family="debian", name="13.7", result_type="debian", result_class="os-pkgs"):
        path = self.root / "report.json"
        path.write_text(json.dumps({"SchemaVersion": 2, "ArtifactType": "container_image", "ArtifactName": "candidate@sha256:test",
                                   "Metadata": {"OS": {"Family": family, "Name": name}},
                                   "Results": [{"Target": "Debian 13.7", "Type": result_type, "Class": result_class,
                                                "Vulnerabilities": findings if findings is not None else [self.finding]}]}))
        return path

    def evaluate(self, path):
        return security_gate.evaluate([path], self.policy, self.today)

    def test_no_policy_remains_strict(self):
        path = self.report([{**self.finding, "Severity": "HIGH"}])
        self.assertFalse(security_gate.evaluate([path])[0])
        self.assertFalse(security_gate.evaluate([self.report()])[0])

    def test_exact_unfixed_critical_assessment_accepts_risk(self):
        passed, lines = self.evaluate(self.report())
        self.assertTrue(passed)
        self.assertIn("assessed_critical=1", lines[0])
        self.assertIn("ASSESSED CRITICAL RISK", lines[0])
        self.assertIn(self.assessment["source"], lines[0])
        self.assertIn("expires=2026-11-10", lines[0])

    def test_fixed_critical_cannot_be_assessed(self):
        path = self.report([{**self.finding, "FixedVersion": "patched"}])
        self.assertFalse(self.evaluate(path)[0])

    def test_fixed_high_blocks_unfixed_high_is_deferred(self):
        for fixed in [None, "", "   "]:
            with self.subTest(fixed=fixed):
                passed, lines = self.evaluate(self.report([{**self.finding, "Severity": "HIGH", "FixedVersion": fixed}]))
                self.assertTrue(passed)
                self.assertIn("DEFERRED HIGH RISK", lines[0])
                self.assertIn("deferred_high=1", lines[0])
        self.assertFalse(self.evaluate(self.report([{**self.finding, "Severity": "HIGH", "FixedVersion": "patched"}]))[0])

    def test_assessment_wrong_package_version_or_cve_blocks(self):
        for key, value in [("PkgName", "another"), ("InstalledVersion", "new-version"), ("VulnerabilityID", "CVE-2026-9999")]:
            with self.subTest(key=key):
                self.assertFalse(self.evaluate(self.report([{**self.finding, key: value}]))[0])

    def test_wrong_os_or_scan_type_blocks(self):
        for scope in [{"family": "alpine"}, {"name": "14.0"}, {"name": "unknown"}, {"result_type": "alpine"}, {"result_class": "lang-pkgs"}]:
            with self.subTest(scope=scope):
                self.assertFalse(self.evaluate(self.report(**scope))[0])

    def test_expired_or_same_day_assessment_blocks(self):
        for expiry in ["2026-10-10", "2026-10-11"]:
            with self.subTest(expiry=expiry):
                self.assessment["expires"] = expiry
                self.assertFalse(self.evaluate(self.report())[0])

    def test_malformed_policy_fails_closed(self):
        import copy
        bad_policies = [{}, {**self.policy, "mode": "ignore"}, {**self.policy, "schema_version": 2}, {**self.policy, "schema_version": True}]
        for key, value in [("id", "CVE-*"), ("owner", " "), ("source", "http://vendor.invalid"), ("expires", "2026-13-10"), ("os_major", "*"), ("assessment", "not affected")]:
            bad = copy.deepcopy(self.policy)
            bad["critical_assessments"][0][key] = value
            bad_policies.append(bad)
        for policy in bad_policies:
            with self.subTest(policy=policy):
                self.assertFalse(security_gate.evaluate([self.report()], policy, self.today)[0])

    def test_duplicate_assessment_and_unknown_fields_fail_closed(self):
        self.assertFalse(security_gate.evaluate([self.report()], {**self.policy, "critical_assessments": [self.assessment, self.assessment]}, self.today)[0])
        self.assertFalse(security_gate.evaluate([self.report()], {**self.policy, "ignore": ["CVE-*"]}, self.today)[0])

    def test_malformed_fixed_version_and_missing_report_fail_closed(self):
        self.assertFalse(self.evaluate(self.report([{**self.finding, "FixedVersion": 42}]))[0])
        self.assertFalse(self.evaluate(self.root / "absent.json")[0])

    def test_cli_null_policy_fails_closed_even_clean_report(self):
        from unittest.mock import patch
        policy = self.root / "policy.json"
        policy.write_text("null")
        report = self.report([])
        with patch.object(sys, "argv", ["security_gate.py", "--policy", str(policy), str(report)]):
            self.assertEqual(security_gate.main(), 1)
