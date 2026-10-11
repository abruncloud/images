#!/usr/bin/env python3
"""Fail closed on HIGH/CRITICAL findings or incomplete Trivy image reports."""
import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

SEVERITIES = {"UNKNOWN", "LOW", "MEDIUM", "HIGH", "CRITICAL"}
BLOCKING = {"HIGH", "CRITICAL"}

def inspect_report(path):
    report = json.loads(Path(path).read_text())
    if not isinstance(report, dict) or report.get("SchemaVersion") != 2:
        raise ValueError("Unsupported or missing Trivy schema")
    if report.get("ArtifactType") != "container_image" or not report.get("ArtifactName"):
        raise ValueError("Expected a complete container image report")
    results = report.get("Results")
    if not isinstance(results, list):
        raise ValueError("Missing or malformed scan results")
    counts = Counter()
    details = []
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
            counts[finding["Severity"]] += 1
            if finding["Severity"] in BLOCKING:
                clean = lambda value: str(value).replace("\n", " ")
                details.append(f"{clean(result.get('Target', 'unknown target'))}: {clean(finding.get('PkgName', 'unknown package'))} {clean(finding.get('VulnerabilityID', 'unknown CVE'))} {finding['Severity']}")
    return counts, details

def evaluate(paths):
    lines = []
    passed = True
    for path in paths:
        try:
            counts, details = inspect_report(path)
            blocked = sum(counts[level] for level in BLOCKING)
            passed = passed and blocked == 0
            line = f"{Path(path).name}: HIGH={counts['HIGH']}, CRITICAL={counts['CRITICAL']}; " + ("BLOCKED" if blocked else "PASS")
            if details:
                line += "\n" + "\n".join("  - " + detail for detail in details[:10])
                if len(details) > 10:
                    line += f"\n  - {len(details) - 10} additional blocking findings; see complete JSON artifact."
            lines.append(line)
        except (OSError, ValueError, TypeError) as error:
            passed = False
            lines.append(f"{Path(path).name}: BLOCKED — {error}")
    return passed, lines

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+", type=Path)
    args = parser.parse_args()
    passed, lines = evaluate(args.reports)
    for line in lines:
        print(line)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as output:
            output.write("\nSecurity policy: all HIGH and CRITICAL vulnerabilities block promotion, including findings without an available fix. Complete JSON reports are attached as artifacts.\n\n")
            output.write("\n".join("- " + line for line in lines) + "\n")
    return 0 if passed else 1

if __name__ == "__main__":
    sys.exit(main())
