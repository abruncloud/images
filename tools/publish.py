#!/usr/bin/env python3
"""Promote already tested native digests without rebuilding any image."""
import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from release import load, tags, targets

REPOSITORY = "abruncloud/postgres"
CANDIDATE_REPOSITORY = "ghcr.io/abruncloud/postgres-ci"

def command(*args):
    return subprocess.check_output(args, text=True).strip()

def current_main():
    return command("gh", "api", "repos/" + os.environ["REPOSITORY"] + "/commits/main", "--jq", ".sha")

def copy_verified(source, destination):
    """Copy manifests and blobs by digest without creating any public tag."""
    expected = source.rsplit("@", 1)[1]
    command("crane", "copy", source, destination)
    observed = command("crane", "digest", destination)
    if observed != expected:
        raise ValueError("Cross-registry digest changed during copy")


def main(target_filter="all", image="postgres"):
    if image not in {"postgres", "mysql", "redis", "clickhouse"}:
        raise ValueError("Unsupported image product")
    repository = "abruncloud/" + image
    candidate_repository = "ghcr.io/abruncloud/" + image + "-ci"
    if target_filter not in {"all", "runtime", "backup"}:
        raise ValueError("Unsupported publication target")
    sha = os.environ["EXPECTED_SHA"]
    if not re.fullmatch(r"[a-f0-9]{40}", sha):
        raise ValueError("Invalid source commit")
    if current_main() != sha:
        raise SystemExit("Refusing stale publication: main advanced while candidates built")
    run_id = os.environ["GITHUB_RUN_ID"]
    attempt = os.environ["GITHUB_RUN_ATTEMPT"]
    if not run_id.isdigit() or not attempt.isdigit():
        raise ValueError("Invalid workflow run identity")
    build_id = sha + "-" + run_id + "-" + attempt
    metadata, lock = load() if image == "postgres" else load(image)
    outputs = []
    # Assemble and sign every candidate before moving any public version alias.
    for release in lock["releases"]:
        for target in targets(metadata, release):
            if target_filter != "all" and target != target_filter:
                continue
            refs = []
            candidate_refs = []
            for arch in ["amd64", "arm64"]:
                path = Path("digests") / (release["major"] + "-" + release["variant"] + "-" + target + "-" + arch)
                digest = path.read_text().strip()
                if not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
                    raise ValueError("Invalid qualified digest: " + str(path))
                candidate_refs.append(candidate_repository + "@" + digest)
                refs.append(repository + "@" + digest)
                copy_verified(candidate_refs[-1], refs[-1])
                command("cosign", "sign", "--yes", refs[-1])
            candidate = candidate_repository + ":build-" + build_id + "-" + release["major"] + "-" + release["variant"] + ("-backup" if target == "backup" else "")
            command("docker", "buildx", "imagetools", "create", "--tag", candidate, *candidate_refs)
            # Obtain the authoritative index digest from registry metadata.
            info = json.loads(command("docker", "buildx", "imagetools", "inspect", candidate, "--format", "{{json .Manifest}}"))
            digest = info["digest"]
            if not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
                raise ValueError("Invalid multi-platform digest")
            candidate_reference = candidate_repository + "@" + digest
            reference = repository + "@" + digest
            copy_verified(candidate_reference, reference)
            command("cosign", "sign", "--yes", reference)
            outputs.append({"major": release["major"], "variant": release["variant"], "target": target,
                            "digest": digest, "native_refs": refs, "candidate_native_refs": candidate_refs,
                            "candidate_ref": candidate_reference, "candidate_archive_tag": candidate, "tags": (tags(release["major"], release["variant"], target) if image == "postgres" else tags(release["major"], release["variant"], target, image))})
    if not outputs:
        raise ValueError("No qualified artifacts for selected publication target")
    if current_main() != sha:
        raise SystemExit("Refusing alias promotion: main advanced during signing")
    for output in outputs:
        for tag in output["tags"]:
            command("docker", "buildx", "imagetools", "create", "--prefer-index=false", "--tag", tag,
                    repository + "@" + output["digest"])
    Path("release.json").write_text(json.dumps({"schema_version": 1, "image": image, "publication_target": target_filter, "source_commit": sha, "build_id": build_id,
                                               "workflow_run_id": run_id, "workflow_run_attempt": attempt,
                                               "inputs": lock, "candidate_repository": candidate_repository, "images": outputs}, indent=2) + "\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", choices=["postgres", "mysql", "redis", "clickhouse"], default="postgres")
    parser.add_argument("--target", choices=["all", "runtime", "backup"], default="all")
    args = parser.parse_args()
    main(args.target, args.image)
