#!/usr/bin/env python3
"""Validate scan reports; strict unless an explicitly selected policy is supplied."""
import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

SEVERITIES = {"UNKNOWN", "LOW", "MEDIUM", "HIGH", "CRITICAL"}
ASSESSMENT_FIELDS = {"id", "os_family", "os_major", "pkg_name", "installed_version", "assessment", "source", "reason", "owner", "expires"}

def validate_policy(policy):
    if not isinstance(policy, dict) or set(policy) != {"schema_version", "mode", "critical_assessments"}:
        raise ValueError("Malformed security policy fields")
    if type(policy["schema_version"]) is not int or policy["schema_version"] != 1 or policy["mode"] != "actionable" or not isinstance(policy["critical_assessments"], list):
        raise ValueError("Unsupported security policy")
    identities = set()
    for item in policy["critical_assessments"]:
        if not isinstance(item, dict) or set(item) != ASSESSMENT_FIELDS:
            raise ValueError("Malformed critical assessment fields")
        if any(not isinstance(value, str) or not value.strip() or "*" in value for value in item.values()):
            raise ValueError("Critical assessments require exact nonempty fields")
        if not re.fullmatch(r"CVE-\d{4}-\d{4,}", item["id"]) or not re.fullmatch(r"[a-z0-9_-]+", item["os_family"]) or not re.fullmatch(r"\d+", item["os_major"]):
            raise ValueError("Malformed assessment identity or OS scope")
        source = urlparse(item["source"])
        if source.scheme != "https" or not source.hostname or source.username or source.password:
            raise ValueError("Assessment requires a reviewable HTTPS vendor source")
        if "not-affected" in item["assessment"].lower() or "not affected" in item["assessment"].lower():
            raise ValueError("This policy records accepted risk, not a not-affected claim")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", item["expires"]):
            raise ValueError("Malformed assessment expiry")
        date.fromisoformat(item["expires"])
        identity = tuple(item[key] for key in ["id", "os_family", "os_major", "pkg_name", "installed_version"])
        if identity in identities:
            raise ValueError("Duplicate critical assessment scope")
        identities.add(identity)
    return policy

def assessed(report, result, finding, policy, today):
    operating_system = report.get("Metadata", {}).get("OS", {})
    if not isinstance(operating_system, dict):
        return None
    family, name = operating_system.get("Family"), operating_system.get("Name")
    if not isinstance(name, str) or not re.fullmatch(r"\d+(?:\.\d+)*", name):
        return None
    if result.get("Class") != "os-pkgs" or result.get("Type") != family:
        return None
    for item in policy["critical_assessments"]:
        if (item["id"] == finding.get("VulnerabilityID") and item["os_family"] == family
                and item["os_major"] == name.split(".")[0] and item["pkg_name"] == finding.get("PkgName")
                and item["installed_version"] == finding.get("InstalledVersion")
                and date.fromisoformat(item["expires"]) > today):
            return item
    return None

def inspect_report(path, policy=None, today=None):
    report = json.loads(Path(path).read_text())
    if not isinstance(report, dict) or report.get("SchemaVersion") != 2:
        raise ValueError("Unsupported or missing Trivy schema")
    if report.get("ArtifactType") != "container_image" or not report.get("ArtifactName"):
        raise ValueError("Expected a complete container image report")
    results = report.get("Results")
    if not isinstance(results, list):
        raise ValueError("Missing or malformed scan results")
    counts, details = Counter(), []
    today = today or datetime.now(timezone.utc).date()
    for result in results:
        if not isinstance(result, dict):
            raise ValueError("Malformed scan result")
        vulnerabilities = result.get("Vulnerabilities")
        if vulnerabilities is None:
            continue
        if not isinstance(vulnerabilities, list):
            raise ValueError("Malformed vulnerability collection")
        for finding in vulnerabilities:
            if not isinstance(finding, dict) or finding.get("Severity") not in SEVERITIES:
                raise ValueError("Malformed vulnerability severity")
            fixed = finding.get("FixedVersion")
            if fixed is not None and not isinstance(fixed, str):
                raise ValueError("Malformed fixed version")
            fixed = bool(fixed and fixed.strip())
            severity = finding["Severity"]
            counts[severity] += 1
            if severity not in {"HIGH", "CRITICAL"}:
                continue
            status = "BLOCKED"
            assessment = None
            if policy is not None:
                if severity == "HIGH" and not fixed:
                    status = "DEFERRED HIGH RISK"
                    counts["DEFERRED_HIGH"] += 1
                elif severity == "CRITICAL" and not fixed:
                    assessment = assessed(report, result, finding, policy, today)
                    if assessment:
                        status = "ASSESSED CRITICAL RISK"
                        counts["ASSESSED_CRITICAL"] += 1
            if status == "BLOCKED":
                counts["BLOCKED"] += 1
            clean = lambda value: str(value).replace("\n", " ")
            detail = f"{status}: {clean(result.get('Target', 'unknown target'))}: {clean(finding.get('PkgName', 'unknown package'))} {clean(finding.get('VulnerabilityID', 'unknown CVE'))} {severity}"
            if assessment:
                detail += f"; vendor={assessment['assessment']}; owner={assessment['owner']}; expires={assessment['expires']}; source={assessment['source']}; reason={assessment['reason']}"
            details.append((status != "BLOCKED", detail))
    return counts, [detail for _, detail in sorted(details, key=lambda item: item[0])]

def evaluate(paths, policy=None, today=None):
    lines, passed = [], True
    if policy is not None:
        try:
            validate_policy(policy)
        except (ValueError, TypeError) as error:
            return False, [f"Policy BLOCKED — {error}"]
    for path in paths:
        try:
            counts, details = inspect_report(path, policy, today)
            blocked = counts["BLOCKED"]
            passed = passed and blocked == 0
            line = f"{Path(path).name}: HIGH={counts['HIGH']}, CRITICAL={counts['CRITICAL']}, blocked={blocked}, deferred_high={counts['DEFERRED_HIGH']}, assessed_critical={counts['ASSESSED_CRITICAL']}; " + ("BLOCKED" if blocked else "PASS")
            if details:
                line += "\n" + "\n".join("  - " + detail for detail in details[:10])
                if len(details) > 10:
                    line += f"\n  - {len(details) - 10} additional findings; see complete JSON artifact."
            lines.append(line)
        except (OSError, ValueError, TypeError, AttributeError) as error:
            passed = False
            lines.append(f"{Path(path).name}: BLOCKED — {error}")
    return passed, lines

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, help="Explicit reviewed actionable-risk policy; omitted means strict")
    parser.add_argument("reports", nargs="+", type=Path)
    args = parser.parse_args()
    policy = None
    if args.policy:
        try:
            policy = json.loads(args.policy.read_text())
            validate_policy(policy)
        except (OSError, ValueError) as error:
            print(f"Policy BLOCKED — {error}")
            return 1
    passed, lines = evaluate(args.reports, policy)
    for line in lines:
        print(line)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        text = ("Actionable policy: block CRITICAL and fixed HIGH findings. Unfixed HIGH findings are deferred risks; exact, unexpired vendor assessments may accept unfixed CRITICAL risk. This is risk acceptance, not proof of safety."
                if policy is not None else "Strict policy: all HIGH and CRITICAL findings block, including those without a fix.")
        with open(summary, "a") as output:
            output.write("\n" + text + " Complete JSON reports are attached as artifacts.\n\n")
            output.write("\n".join("- " + line for line in lines) + "\n")
    return 0 if passed else 1

if __name__ == "__main__":
    sys.exit(main())
