#!/usr/bin/env python3
"""Render committed Dockerfiles from locked inputs; --check detects drift."""
import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
IMAGE = ROOT / "images" / "postgres"


def rendered_files():
    lock = json.loads((IMAGE / "versions.lock.json").read_text())
    metadata = json.loads((IMAGE / "image.json").read_text())
    if lock.get("schema_version") != 1:
        raise ValueError("unsupported lock schema")
    backup_variant = metadata.get("backup_variant")
    if backup_variant not in metadata["variants"] or not backup_variant.startswith("alpine"):
        raise ValueError("backup variant must be a supported Alpine distribution")
    vector = lock["pgvector"]
    if not re.fullmatch(r"[0-9a-f]{64}", vector["sha256"]):
        raise ValueError("pgvector must have a SHA256 checksum")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", vector["version"]):
        raise ValueError("pgvector must be a stable release")
    expected_url = f"https://github.com/pgvector/pgvector/archive/refs/tags/v{vector['version']}.tar.gz"
    if vector["url"] != expected_url:
        raise ValueError("pgvector download must match the official release archive")
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
        if not re.fullmatch(r"[0-9]+\.[0-9]+", release["postgres_version"]):
            raise ValueError("only stable PostgreSQL versions are supported")
        if release["postgres_version"].split(".")[0] != major:
            raise ValueError("PostgreSQL version and major disagree")
        source = re.fullmatch(r"(?:docker.io/)?(?:library/)?postgres:([a-zA-Z0-9_.-]+)@sha256:[0-9a-f]{64}", release["base_image"])
        if source is None:
            raise ValueError("base must be an exact official PostgreSQL image digest")
        if source[1] != f"{release['postgres_version']}-{variant}":
            raise ValueError("base tag must match the locked version and distribution")
        backup_enabled = variant == backup_variant
        if backup_enabled:
            expected_backup = "docker.io/library/alpine:" + variant.removeprefix("alpine")
            if not re.fullmatch(re.escape(expected_backup) + r"@sha256:[0-9a-f]{64}", release.get("backup_base_image", "")):
                raise ValueError("backup base must match its pinned official distribution")
        elif "backup_base_image" in release:
            raise ValueError("runtime-only distribution must not declare a backup base")
        if not release["platforms"] or not set(release["platforms"]).issubset(metadata["platforms"]):
            raise ValueError("unsupported platforms")
        values = {
            "BASE_IMAGE": release["base_image"],
            "BACKUP_BASE_IMAGE": release.get("backup_base_image", ""),
            "POSTGRES_MAJOR": major,
            "GOSU_BUILD": gosu_fragment,
            "GOSU_VERSION": gosu["version"],
            "GOSU_URL": gosu["url"],
            "GOSU_SHA256": gosu["sha256"],
            "GO_VERSION": compiler["version"],
            "GO_BASE_IMAGE": compiler["base_image"],
            "POSTGRES_VERSION": release["postgres_version"],
            "PGVECTOR_VERSION": vector["version"],
            "PGVECTOR_URL": vector["url"],
            "PGVECTOR_SHA256": vector["sha256"],
        }
        family = "alpine" if variant.startswith("alpine") else "debian"
        recipes = [("Dockerfile", f"Dockerfile.{family}")]
        if backup_enabled:
            recipes.append(("Dockerfile.backup", "Dockerfile.backup.alpine"))
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
