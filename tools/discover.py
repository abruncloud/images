#!/usr/bin/env python3
"""Resolve trusted upstream releases into an exact, reviewable lock file."""
import argparse
import hashlib
import json
import os
import re
import urllib.request
from urllib.parse import urlparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACCEPT = ", ".join(["application/vnd.oci.image.index.v1+json", "application/vnd.docker.distribution.manifest.list.v2+json"])

def fetch(url, headers=None):
    request = urllib.request.Request(url, headers={"User-Agent": "abruncloud-images-discovery", **(headers or {})})
    origin = urlparse(url)
    token = os.environ.get("GH_TOKEN")
    if (token and origin.scheme == "https" and origin.hostname == "api.github.com"
            and origin.port in {None, 443} and origin.username is None and origin.password is None):
        # urllib redirects copy ordinary headers, but omit unredirected headers.
        # Never forward the GitHub token, even to a same-host redirect.
        request.add_unredirected_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read(), response.headers

def resolve(tag, repository="postgres"):
    if repository not in {"postgres", "golang"}:
        raise ValueError("Unsupported official image repository")
    token = json.loads(fetch("https://auth.docker.io/token?service=registry.docker.io&scope=repository:library/" + repository + ":pull")[0])["token"]
    raw, headers = fetch("https://registry-1.docker.io/v2/library/" + repository + "/manifests/" + tag,
                         {"Authorization": "Bearer " + token, "Accept": ACCEPT})
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    if headers.get("Docker-Content-Digest") != digest:
        raise ValueError("Registry manifest digest verification failed")
    platforms = {"linux/" + item["platform"]["architecture"] for item in json.loads(raw).get("manifests", [])
                 if item.get("platform", {}).get("os") == "linux"}
    required = ["linux/amd64", "linux/arm64"]
    if not set(required) <= platforms:
        raise ValueError("Required native platforms unavailable: " + tag)
    return "docker.io/library/" + repository + ":" + tag + "@" + digest, required

def review_inputs(lock):
    """Only PostgreSQL/base changes and same-line Go patches are routine."""
    inputs = {key: value for key, value in lock.items() if key != "releases"}
    compiler = lock["go"]
    version = compiler["version"]
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Expected a stable Go compiler version")
    match = re.fullmatch(r"docker\.io/library/golang:" + re.escape(version) + r"-([a-z0-9][a-z0-9.-]*)@sha256:[a-f0-9]{64}", compiler["base_image"])
    if not match:
        raise ValueError("Expected a matching pinned official Go compiler image")
    inputs["go"] = {key: value for key, value in compiler.items() if key not in {"version", "base_image"}}
    inputs["go"].update({"release_line": ".".join(version.split(".")[:2]), "distribution": match.group(1)})
    return inputs

def discover_hardening(current):
    latest = json.loads(fetch("https://api.github.com/repos/tianon/gosu/releases/latest")[0])
    version = latest.get("tag_name", "")
    if latest.get("draft") or latest.get("prerelease") or not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", version):
        raise ValueError("Expected a stable numeric gosu release")
    url = "https://github.com/tianon/gosu/archive/refs/tags/" + version + ".tar.gz"
    gosu = {**current["gosu"], "version": version, "url": url, "sha256": hashlib.sha256(fetch(url)[0]).hexdigest()}
    # Keep the reviewed compiler distribution as new stable releases appear.
    match = re.fullmatch(r"docker\.io/library/golang:[0-9.]+-([a-z0-9][a-z0-9.-]*)@sha256:[a-f0-9]{64}",
                         current["go"]["base_image"])
    if not match:
        raise ValueError("Expected a pinned official Go compiler image")
    upstream = fetch("https://raw.githubusercontent.com/docker-library/official-images/master/library/golang")[0].decode()
    versions = re.findall(r"(?<![\w.])(\d+\.\d+\.\d+)-" + re.escape(match.group(1)) + r"(?=[,\s]|$)", upstream)
    if not versions:
        raise ValueError("No stable official Go toolchain release available")
    version = max(versions, key=lambda value: tuple(map(int, value.split("."))))
    image, _ = resolve(version + "-" + match.group(1), repository="golang")
    return gosu, {**current["go"], "version": version, "base_image": image}

def discover():
    metadata = json.loads((ROOT / "images/postgres/image.json").read_text())
    current = json.loads((ROOT / "images/postgres/versions.lock.json").read_text())
    upstream = fetch("https://raw.githubusercontent.com/docker-library/official-images/master/library/postgres")[0].decode()
    records = []
    for major in metadata["supported_majors"]:
        for variant in metadata["variants"]:
            versions = re.findall(r"(?<![\w.])(" + re.escape(str(major)) + r"\.\d+)-" + re.escape(variant) + r"(?=[,\s]|$)", upstream)
            if not versions:
                raise ValueError("Unsupported official PostgreSQL variant: " + str(major) + "/" + variant)
            version = max(versions, key=lambda value: tuple(map(int, value.split("."))))
            image, platforms = resolve(version + "-" + variant)
            records.append({"postgres_version": version, "major": str(major), "variant": variant,
                            "base_image": image, "platforms": platforms})
    tags = json.loads(fetch("https://api.github.com/repos/pgvector/pgvector/tags?per_page=100")[0])
    versions = [tag["name"][1:] for tag in tags if re.fullmatch(r"v\d+\.\d+\.\d+", tag["name"])]
    version = max(versions, key=lambda value: tuple(map(int, value.split("."))))
    url = "https://github.com/pgvector/pgvector/archive/refs/tags/v" + version + ".tar.gz"
    checksum = hashlib.sha256(fetch(url)[0]).hexdigest()
    gosu, go = discover_hardening(current)
    return {**current, "schema_version": 1, "pgvector": {**current["pgvector"], "version": version, "url": url, "sha256": checksum},
            "gosu": gosu, "go": go, "releases": records}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if upstream differs; do not change the lock")
    parser.add_argument("--review-inputs", action="store_true", help="Print pinned non-routine inputs without network discovery")
    args = parser.parse_args()
    output = ROOT / "images/postgres/versions.lock.json"
    if args.review_inputs:
        print(json.dumps(review_inputs(json.loads(output.read_text())), sort_keys=True, separators=(",", ":")))
        return
    content = json.dumps(discover(), indent=2) + "\n"
    if args.check:
        if not output.exists() or output.read_text() != content:
            raise SystemExit("Upstream changed; run tools/discover.py and review the update")
    else:
        output.write_text(content)
        print(output.relative_to(ROOT))

if __name__ == "__main__":
    main()
