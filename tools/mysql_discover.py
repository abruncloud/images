#!/usr/bin/env python3
"""Discover patches only within explicitly reviewed MySQL LTS release lines."""
import argparse
import json
import re
from pathlib import Path
from discover import fetch, resolve, discover_hardening, review_inputs as hardening_review_inputs

ROOT = Path(__file__).resolve().parents[1]


def review_inputs(lock):
    """Patch versions and verified base rebuilds are routine; new inputs are not."""
    inputs = hardening_review_inputs(lock)
    records = []
    for release in lock["releases"]:
        record = dict(release)
        version = record.pop("mysql_version")
        line = record["major"]
        if "mysql_client_rpm_version" in record:
            rpm = record.pop("mysql_client_rpm_version")
            match = re.fullmatch(re.escape(version) + r"-([0-9]+\.el9)", rpm)
            if not match:
                raise ValueError("Expected matching MySQL client RPM version")
            record["mysql_client_rpm_release"] = match.group(1)
        if not re.fullmatch(re.escape(line) + r"\.\d+", version):
            raise ValueError("MySQL version must remain in the reviewed release line")
        for key, repository in [("base_image", "mysql"), ("backup_base_image", "oraclelinux")]:
            reference = record.pop(key)
            tag = version + "-" + record["variant"] if key == "base_image" else "9-slim"
            if not re.fullmatch(r"docker\.io/library/" + repository + ":" + re.escape(tag) + r"@sha256:[a-f0-9]{64}", reference):
                raise ValueError("Expected matching pinned official MySQL or Oracle Linux image")
        records.append(record)
    inputs["releases"] = records
    return inputs


def discover():
    metadata = json.loads((ROOT / "images/mysql/image.json").read_text())
    current = json.loads((ROOT / "images/mysql/versions.lock.json").read_text())
    if metadata["variants"] != ["oraclelinux9"]:
        raise ValueError("Only reviewed Oracle Linux 9 is supported")
    upstream = fetch("https://raw.githubusercontent.com/docker-library/official-images/master/library/mysql")[0].decode()
    backup_image, backup_platforms = resolve("9-slim", repository="oraclelinux")
    records = []
    for line in metadata["supported_majors"]:
        if not re.fullmatch(r"\d+\.\d+", line):
            raise ValueError("Expected an explicitly reviewed MySQL LTS release line")
        versions = re.findall(r"(?<![\w.])(" + re.escape(line) + r"\.\d+)-oraclelinux9(?=[,\s]|$)", upstream)
        if not versions:
            raise ValueError("Reviewed MySQL release line unavailable: " + line)
        version = max(versions, key=lambda value: tuple(map(int, value.split("."))))
        tag = version + "-oraclelinux9"
        stanza = next(block for block in upstream.split("\n\n") if re.search(r"^Tags:.*(?<![\w.])" + re.escape(tag) + r"(?=[,\s]|$)", block, re.MULTILINE))
        commit = re.search(r"^GitCommit: ([a-f0-9]{40})$", stanza, re.MULTILINE)
        directory = re.search(r"^Directory: (.+)$", stanza, re.MULTILINE)
        if not commit or not directory or directory.group(1) != line or "File: Dockerfile.oracle" not in stanza:
            raise ValueError("Expected reviewed official MySQL source metadata")
        dockerfile = fetch("https://raw.githubusercontent.com/docker-library/mysql/" + commit.group(1) + "/" + line + "/Dockerfile.oracle")[0].decode()
        rpm = re.search(r"^ENV MYSQL_VERSION (" + re.escape(version) + r"-[0-9]+\.el9)$", dockerfile, re.MULTILINE)
        if not rpm:
            raise ValueError("Official MySQL client RPM does not match the discovered version")
        image, platforms = resolve(tag, repository="mysql")
        if platforms != backup_platforms:
            raise ValueError("Backup and server platform support differ")
        previous = next(item for item in current["releases"] if item["major"] == line and item["variant"] == "oraclelinux9")
        records.append({**previous, "mysql_version": version, "major": line, "variant": "oraclelinux9",
                        "base_image": image, "backup_base_image": backup_image, "mysql_client_rpm_version": rpm.group(1), "platforms": platforms})
    gosu, go = discover_hardening(current)
    return {**current, "gosu": gosu, "go": go, "releases": records}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--review-inputs", action="store_true")
    args = parser.parse_args()
    output = ROOT / "images/mysql/versions.lock.json"
    if args.review_inputs:
        print(json.dumps(review_inputs(json.loads(output.read_text())), sort_keys=True, separators=(",", ":")))
        return
    content = json.dumps(discover(), indent=2) + "\n"
    if args.check:
        if output.read_text() != content:
            raise SystemExit("Upstream changed; run tools/mysql_discover.py and review the update")
    else:
        output.write_text(content)
        print(output.relative_to(ROOT))


if __name__ == "__main__":
    main()
