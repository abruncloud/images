#!/usr/bin/env python3
"""Promote already tested native digests without rebuilding any image."""
import json
import os
import re
import subprocess
from pathlib import Path
from release import load, tags

REPOSITORY = "abruncloud/postgres"

def command(*args):
    return subprocess.check_output(args, text=True).strip()

def current_main():
    return command("gh", "api", "repos/" + os.environ["REPOSITORY"] + "/commits/main", "--jq", ".sha")

def main():
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
    _, lock = load()
    outputs = []
    # Assemble and sign every candidate before moving any public version alias.
    for release in lock["releases"]:
        for target in ["runtime", "backup"]:
            refs = []
            for arch in ["amd64", "arm64"]:
                path = Path("digests") / (release["major"] + "-" + release["variant"] + "-" + target + "-" + arch)
                digest = path.read_text().strip()
                if not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
                    raise ValueError("Invalid qualified digest: " + str(path))
                refs.append(REPOSITORY + "@" + digest)
                command("cosign", "sign", "--yes", refs[-1])
            candidate = REPOSITORY + ":build-" + build_id + "-" + release["major"] + "-" + release["variant"] + ("-backup" if target == "backup" else "")
            command("docker", "buildx", "imagetools", "create", "--tag", candidate, *refs)
            # Obtain the authoritative index digest from registry metadata.
            info = json.loads(command("docker", "buildx", "imagetools", "inspect", candidate, "--format", "{{json .Manifest}}"))
            digest = info["digest"]
            if not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
                raise ValueError("Invalid multi-platform digest")
            reference = REPOSITORY + "@" + digest
            command("cosign", "sign", "--yes", reference)
            outputs.append({"major": release["major"], "variant": release["variant"], "target": target,
                            "digest": digest, "native_refs": refs, "tags": tags(release["major"], release["variant"], target)})
    if current_main() != sha:
        raise SystemExit("Refusing alias promotion: main advanced during signing")
    for output in outputs:
        for tag in output["tags"]:
            command("docker", "buildx", "imagetools", "create", "--prefer-index=false", "--tag", tag,
                    REPOSITORY + "@" + output["digest"])
    Path("release.json").write_text(json.dumps({"schema_version": 1, "source_commit": sha, "build_id": build_id,
                                               "workflow_run_id": run_id, "workflow_run_attempt": attempt,
                                               "inputs": lock, "images": outputs}, indent=2) + "\n")

if __name__ == "__main__":
    main()
