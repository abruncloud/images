#!/usr/bin/env python3
"""Resolve trusted upstream releases into an exact, reviewable lock file."""
import argparse
import hashlib
import json
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACCEPT = ", ".join(["application/vnd.oci.image.index.v1+json", "application/vnd.docker.distribution.manifest.list.v2+json"])

def fetch(url, headers=None):
    request = urllib.request.Request(url, headers={"User-Agent": "abruncloud-images-discovery", **(headers or {})})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read(), response.headers

def resolve(tag):
    token = json.loads(fetch("https://auth.docker.io/token?service=registry.docker.io&scope=repository:library/postgres:pull")[0])["token"]
    raw, headers = fetch("https://registry-1.docker.io/v2/library/postgres/manifests/" + tag,
                         {"Authorization": "Bearer " + token, "Accept": ACCEPT})
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    if headers.get("Docker-Content-Digest") != digest:
        raise ValueError("Registry manifest digest verification failed")
    platforms = {"linux/" + item["platform"]["architecture"] for item in json.loads(raw).get("manifests", [])
                 if item.get("platform", {}).get("os") == "linux"}
    required = ["linux/amd64", "linux/arm64"]
    if not set(required) <= platforms:
        raise ValueError("Required native platforms unavailable: " + tag)
    return "docker.io/library/postgres:" + tag + "@" + digest, required

def discover():
    metadata = json.loads((ROOT / "images/postgres/image.json").read_text())
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
    return {"schema_version": 1, "pgvector": {"version": version, "url": url, "sha256": checksum}, "releases": records}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if upstream differs; do not change the lock")
    args = parser.parse_args()
    output = ROOT / "images/postgres/versions.lock.json"
    content = json.dumps(discover(), indent=2) + "\n"
    if args.check:
        if not output.exists() or output.read_text() != content:
            raise SystemExit("Upstream changed; run tools/discover.py and review the update")
    else:
        output.write_text(content)
        print(output.relative_to(ROOT))

if __name__ == "__main__":
    main()
