#!/usr/bin/env python3
"""Render reviewed Redis client recipes from exact upstream inputs."""
import argparse
import json
from pathlib import Path
import re
ROOT = Path(__file__).resolve().parents[1]
IMAGE = ROOT / "images/redis"
def rendered_files():
    metadata = json.loads((IMAGE / "image.json").read_text())
    lock = json.loads((IMAGE / "versions.lock.json").read_text())
    if lock.get("schema_version") != 1 or metadata.get("targets") != ["backup"]:
        raise ValueError("Only client-only backup targets are reviewed")
    if metadata["variants"] != ["alpine3.22"] or metadata["backup_variant"] != "alpine3.22":
        raise ValueError("Only Alpine 3.22 client tools are reviewed")
    seen = set()
    for release in lock["releases"]:
        major, variant, version = release["major"], release["variant"], release["redis_version"]
        key = (major, variant)
        if key in seen or major not in metadata["supported_majors"] or variant != "alpine3.22":
            raise ValueError("Unexpected or duplicate release")
        seen.add(key)
        if not re.fullmatch(re.escape(major) + r"\.\d+", version) or release["release_line"] != major:
            raise ValueError("Redis patch must remain in the reviewed release line")
        expected = f"https://github.com/redis/redis/archive/refs/tags/{version}.tar.gz"
        if release["source_url"] != expected or not re.fullmatch(r"[a-f0-9]{64}", release["source_sha256"]):
            raise ValueError("Redis source must match its official checksum-verified archive")
        if not re.fullmatch(r"[a-f0-9]{40}", release["official_source_commit"]):
            raise ValueError("Official source commit must be pinned")
        if not re.fullmatch(re.escape(f"docker.io/library/redis:{version}-bookworm") + r"@sha256:[a-f0-9]{64}", release["base_image"]):
            raise ValueError("Server fixture must be the pinned official Redis release")
        if not re.fullmatch(r"docker.io/library/alpine:3\.22@sha256:[a-f0-9]{64}", release["backup_base_image"]):
            raise ValueError("Client distribution must be pinned Alpine 3.22")
        if release["platforms"] != ["linux/amd64", "linux/arm64"]:
            raise ValueError("Both native architectures are required")
        text = (IMAGE / "templates/Dockerfile.backup.alpine3.22").read_text()
        for token, keyname in {"BACKUP_BASE_IMAGE":"backup_base_image", "SOURCE_URL":"source_url", "SOURCE_SHA256":"source_sha256", "REDIS_VERSION":"redis_version"}.items():
            text = text.replace("{{" + token + "}}", release[keyname])
        if re.search(r"\{\{[^}]+\}\}", text):
            raise ValueError("Unresolved recipe token")
        yield IMAGE / "generated" / major / variant / "Dockerfile.backup", text
    if seen != {(major, "alpine3.22") for major in metadata["supported_majors"]}:
        raise ValueError("Lock must contain every reviewed release")
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = dict(rendered_files())
    changed = []
    for path, content in expected.items():
        if not path.exists() or path.read_text() != content:
            changed.append(str(path.relative_to(ROOT)))
            if not args.check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
    for stale in (IMAGE / "generated").rglob("Dockerfile*"):
        if stale not in expected:
            changed.append(str(stale.relative_to(ROOT)))
            if not args.check: stale.unlink()
    if args.check and changed:
        raise SystemExit("Generated recipes differ: " + ", ".join(changed))
    print(f"{'Checked' if args.check else 'Generated'} {len(expected)} Dockerfiles")
if __name__ == "__main__":
    main()
