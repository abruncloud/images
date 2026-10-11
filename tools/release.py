#!/usr/bin/env python3
"""Generate CI matrices and standard Docker tags from reviewed image metadata."""
import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def load():
    metadata = json.loads((ROOT / "images/postgres/image.json").read_text())
    lock = json.loads((ROOT / "images/postgres/versions.lock.json").read_text())
    return metadata, lock

def matrix():
    _, lock = load()
    entries = []
    for release in lock["releases"]:
        for arch in ["amd64", "arm64"]:
            entries.append({**release, "arch": arch, "runner": "ubuntu-24.04" + ("-arm" if arch == "arm64" else ""),
                            "directory": "images/postgres/generated/" + release["major"] + "/" + release["variant"]})
    return {"include": entries}

def tags(major, variant, target):
    metadata, lock = load()
    release = next(item for item in lock["releases"] if item["major"] == major and item["variant"] == variant)
    version = release["postgres_version"]
    values = [version + "-" + variant, major + "-" + variant]
    if variant == metadata["default_variant"]:
        values += [version, major]
    if variant == metadata["default_alpine_variant"]:
        values += [version + "-alpine", major + "-alpine"]
    suffix = "-backup" if target == "backup" else ""
    return ["abruncloud/postgres:" + value + suffix for value in values]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("matrix")
    tag = sub.add_parser("tags")
    tag.add_argument("major")
    tag.add_argument("variant")
    tag.add_argument("target", choices=["runtime", "backup"])
    sub.add_parser("releases")
    args = parser.parse_args()
    if args.command == "matrix":
        print(json.dumps(matrix(), separators=(",", ":")))
    elif args.command == "tags":
        print("\n".join(tags(args.major, args.variant, args.target)))
    else:
        for item in load()[1]["releases"]:
            print(item["major"], item["variant"])

if __name__ == "__main__":
    main()
