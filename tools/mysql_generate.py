#!/usr/bin/env python3
"""Render committed Dockerfiles from locked inputs; --check detects drift."""
import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
IMAGE = ROOT / "images" / "mysql"


def rendered_files():
    lock = json.loads((IMAGE / "versions.lock.json").read_text())
    metadata = json.loads((IMAGE / "image.json").read_text())
    if lock.get("schema_version") != 1:
        raise ValueError("unsupported lock schema")
    backup_variant = metadata.get("backup_variant")
    if backup_variant != "oraclelinux9" or metadata["variants"] != ["oraclelinux9"]:
        raise ValueError("only the supported Oracle Linux 9 distribution is allowed")
    gosu = lock["gosu"]
    compiler = lock["go"]
    if not re.fullmatch(r"[0-9]+\.[0-9]+", gosu["version"]):
        raise ValueError("gosu must be a stable upstream release")
    if gosu["url"] != f"https://github.com/tianon/gosu/archive/refs/tags/{gosu['version']}.tar.gz":
        raise ValueError("gosu URL must match its official release archive")
    if not re.fullmatch(r"[0-9a-f]{64}", gosu["sha256"]):
        raise ValueError("gosu must have a SHA256 checksum")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", compiler["version"]):
        raise ValueError("Go compiler must be a stable patch release")
    go_source = re.fullmatch(r"docker.io/library/golang:([0-9.]+)-trixie@sha256:[0-9a-f]{64}", compiler["base_image"])
    if go_source is None or go_source[1] != compiler["version"]:
        raise ValueError("Go compiler must match its pinned official image")
    gosu_fragment = (IMAGE / "templates/Dockerfile.gosu").read_text()
    seen = set()
    for release in lock["releases"]:
        major = str(release["major"])
        variant = release["variant"]
        key = (major, variant)
        if key in seen:
            raise ValueError(f"duplicate release {key}")
        seen.add(key)
        if major not in metadata["supported_majors"] or variant not in metadata["variants"]:
            raise ValueError(f"unsupported release {key}")
        version = release["mysql_version"]
        if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
            raise ValueError("only stable MySQL patch releases are supported")
        if ".".join(version.split(".")[:2]) != major or release.get("release_line") != major:
            raise ValueError("MySQL version and release line disagree")
        expected_base = f"docker.io/library/mysql:{version}-{variant}"
        if not re.fullmatch(re.escape(expected_base) + r"@sha256:[0-9a-f]{64}", release["base_image"]):
            raise ValueError("base must match the exact official MySQL version and distribution")
        backup_enabled = variant == backup_variant
        if not re.fullmatch(r"docker.io/library/oraclelinux:9-slim@sha256:[0-9a-f]{64}", release.get("backup_base_image", "")):
            raise ValueError("backup base must be pinned Oracle Linux 9 slim")
        if not re.fullmatch(re.escape(version) + r"-[0-9]+\.el9", release.get("mysql_client_rpm_version", "")):
            raise ValueError("client RPM must match the server patch and distribution")
        if not release["platforms"] or not set(release["platforms"]).issubset(metadata["platforms"]):
            raise ValueError("unsupported platforms")
        values = {
            "BASE_IMAGE": release["base_image"],
            "BACKUP_BASE_IMAGE": release.get("backup_base_image", ""),
            "GOSU_BUILD": gosu_fragment,
            "GOSU_VERSION": gosu["version"],
            "GOSU_URL": gosu["url"],
            "GOSU_SHA256": gosu["sha256"],
            "GO_VERSION": compiler["version"],
            "GO_BASE_IMAGE": compiler["base_image"],
            "MYSQL_VERSION": version,
            "MYSQL_RELEASE_LINE": major,
            "MYSQL_CLIENT_RPM_VERSION": release["mysql_client_rpm_version"],
        }
        recipes = [("Dockerfile", "Dockerfile.oraclelinux9")]
        backup_template = IMAGE / "templates/Dockerfile.backup.oraclelinux9"
        if backup_enabled and backup_template.exists():
            recipes.append(("Dockerfile.backup", backup_template.name))
        for target, template in recipes:
            text = (IMAGE / "templates" / template).read_text()
            for name, value in values.items():
                text = text.replace("{{" + name + "}}", value)
            if re.search(r"\{\{[^}]+\}\}", text):
                raise ValueError(f"unresolved template token in {template}")
            yield IMAGE / "generated" / major / variant / target, text
    required = {(str(major), variant) for major in metadata["supported_majors"] for variant in metadata["variants"]}
    if seen != required:
        raise ValueError("lock must contain every supported major and distribution")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = dict(rendered_files())
    changed = []
    for path, text in expected.items():
        if not path.exists() or path.read_text() != text:
            changed.append(str(path.relative_to(ROOT)))
            if not args.check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
    stale = [path for path in (IMAGE / "generated").rglob("Dockerfile*") if path not in expected]
    for path in stale:
        changed.append(str(path.relative_to(ROOT)))
        if not args.check:
            path.unlink()
    if args.check and changed:
        print("Generated Dockerfiles differ: " + ", ".join(changed), file=sys.stderr)
        return 1
    print(f"{'Checked' if args.check else 'Generated'} {len(expected)} Dockerfiles")
    return 0


if __name__ == "__main__":
    sys.exit(main())
