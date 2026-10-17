#!/usr/bin/env python3
"""Generate CI matrices and standard Docker tags from reviewed image metadata."""
import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def load(image="postgres"):
    if image not in {"postgres", "mysql", "redis"}:
        raise ValueError("Unsupported image product")
    metadata = json.loads((ROOT / ("images/" + image + "/image.json")).read_text())
    lock = json.loads((ROOT / ("images/" + image + "/versions.lock.json")).read_text())
    return metadata, lock

def matrix(target="all", image="postgres"):
    if target not in {"all", "runtime", "backup"}:
        raise ValueError("Unsupported publication target")
    metadata, lock = load() if image == "postgres" else load(image)
    entries = []
    for release in lock["releases"]:
        if target != "all" and target not in targets(metadata, release):
            continue
        for arch in ["amd64", "arm64"]:
            entries.append({**release, "backup": release["variant"] == metadata["backup_variant"], "arch": arch, "runner": "ubuntu-24.04" + ("-arm" if arch == "arm64" else ""),
                            "directory": "images/" + image + "/generated/" + release["major"] + "/" + release["variant"]})
    return {"include": entries}

def targets(metadata, release):
    available = ["runtime", "backup"] if release["variant"] == metadata["backup_variant"] else ["runtime"]
    return [target for target in available if target in metadata.get("targets", available)]

def tags(major, variant, target, image="postgres"):
    metadata, lock = load() if image == "postgres" else load(image)
    release = next(item for item in lock["releases"] if item["major"] == major and item["variant"] == variant)
    if target not in targets(metadata, release):
        raise ValueError("Unsupported image target for distribution")
    version = release[image + "_version"]
    values = [version + "-" + variant, major + "-" + variant]
    if (target == "runtime" and variant == metadata["default_variant"]) or target == "backup":
        values += [version, major]
    if variant == metadata.get("default_alpine_variant"):
        values += [version + "-alpine", major + "-alpine"]
    suffix = "-backup" if target == "backup" else ""
    return [metadata["repository"] + ":" + value + suffix for value in values]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", choices=["postgres", "mysql", "redis"], default="postgres")
    sub = parser.add_subparsers(dest="command", required=True)
    matrix_parser = sub.add_parser("matrix")
    matrix_parser.add_argument("--target", choices=["all", "runtime", "backup"], default="all")
    tag = sub.add_parser("tags")
    tag.add_argument("major")
    tag.add_argument("variant")
    tag.add_argument("target", choices=["runtime", "backup"])
    sub.add_parser("releases")
    args = parser.parse_args()
    if args.command == "matrix":
        print(json.dumps(matrix(args.target, args.image), separators=(",", ":")))
    elif args.command == "tags":
        print("\n".join(tags(args.major, args.variant, args.target, args.image)))
    else:
        for item in load(args.image)[1]["releases"]:
            print(item["major"], item["variant"])

if __name__ == "__main__":
    main()
