#!/usr/bin/env python3
"""Discover Redis patches only within reviewed lines, using official source checksums."""
import argparse
import json
import re
from pathlib import Path
from discover import fetch, resolve
ROOT = Path(__file__).resolve().parents[1]
def review_inputs(lock):
    result = {**lock, "releases": []}
    for release in lock["releases"]:
        version = release["redis_version"]
        if not re.fullmatch(re.escape(release["major"]) + r"\.\d+", version):
            raise ValueError("Redis version must remain in its reviewed line")
        # Patch/base/source checksum updates are qualified routine changes. Any
        # new line, platform, distribution or source host requires manual review.
        if release["source_url"] != f"https://github.com/redis/redis/archive/refs/tags/{version}.tar.gz":
            raise ValueError("Redis source must be its official archive")
        if not re.fullmatch(re.escape(f"docker.io/library/redis:{version}-bookworm") + r"@sha256:[a-f0-9]{64}", release["base_image"]):
            raise ValueError("Server fixture must remain official Redis bookworm")
        if not re.fullmatch(r"docker.io/library/alpine:3\.22@sha256:[a-f0-9]{64}", release["backup_base_image"]):
            raise ValueError("Client base must remain Alpine 3.22")
        result["releases"].append({key:value for key,value in release.items() if key not in {"redis_version", "base_image", "backup_base_image", "source_url", "source_sha256", "official_source_commit"}})
    return result

def discover():
    metadata = json.loads((ROOT / "images/redis/image.json").read_text())
    current = json.loads((ROOT / "images/redis/versions.lock.json").read_text())
    if metadata["variants"] != ["alpine3.22"]:
        raise ValueError("Only reviewed Alpine 3.22 clients are supported")
    upstream = fetch("https://raw.githubusercontent.com/docker-library/official-images/master/library/redis")[0].decode()
    base, platforms = resolve("3.22", repository="alpine")
    records = []
    for line in metadata["supported_majors"]:
        if not re.fullmatch(r"\d+\.\d+", line):
            raise ValueError("Expected explicit Redis release line")
        versions = re.findall(r"(?<![\w.])(" + re.escape(line) + r"\.\d+)-bookworm(?=[,\s]|$)", upstream)
        if not versions: raise ValueError("Reviewed Redis release unavailable: " + line)
        version = max(versions, key=lambda value: tuple(map(int,value.split("."))))
        tag = version + "-bookworm"
        stanza = next(block for block in upstream.split("\n\n") if re.search(r"^Tags:.*(?<![\w.])" + re.escape(tag) + r"(?=[,\s]|$)", block, re.MULTILINE))
        commit = re.search(r"^GitCommit: ([a-f0-9]{40})$", stanza, re.MULTILINE)
        directory = re.search(r"^Directory: (.+)$", stanza, re.MULTILINE)
        if not commit or not directory or directory[1] != "debian":
            raise ValueError("Unexpected official Redis source metadata")
        dockerfile = fetch("https://raw.githubusercontent.com/redis/docker-library-redis/" + commit[1] + "/debian/Dockerfile")[0].decode()
        source = re.search(r"^ARG REDIS_DOWNLOAD_URL=(.+)$", dockerfile, re.MULTILINE)
        checksum = re.search(r"^ARG REDIS_DOWNLOAD_SHA=([a-f0-9]{64})$", dockerfile, re.MULTILINE)
        expected = f"https://github.com/redis/redis/archive/refs/tags/{version}.tar.gz"
        if not source or not checksum or source[1] != expected:
            raise ValueError("Official Redis source URL/checksum drifted")
        archive = fetch(source[1])[0]
        import hashlib
        if hashlib.sha256(archive).hexdigest() != checksum[1]:
            raise ValueError("Official Redis archive checksum mismatch")
        server, server_platforms = resolve(tag, repository="redis")
        if set(platforms) != {"linux/amd64", "linux/arm64"} or server_platforms != platforms:
            raise ValueError("Required native architectures are unavailable")
        previous = next(item for item in current["releases"] if item["major"] == line)
        records.append({**previous, "redis_version": version, "base_image": server, "backup_base_image": base, "source_url": source[1], "source_sha256": checksum[1], "official_source_commit": commit[1], "platforms": platforms})
    return {**current, "releases": records}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--review-inputs", action="store_true")
    args = parser.parse_args()
    output = ROOT / "images/redis/versions.lock.json"
    if args.review_inputs:
        print(json.dumps(review_inputs(json.loads(output.read_text())), sort_keys=True, separators=(",", ":")))
        return
    content = json.dumps(discover(), indent=2) + "\n"
    if args.check:
        if output.read_text() != content: raise SystemExit("Redis upstream changed; discover and qualify the update")
    else:
        output.write_text(content)
        print(output.relative_to(ROOT))
if __name__ == "__main__": main()
