#!/usr/bin/env python3
"""Resolve official MongoDB8.0 patches, Database Tools100.x and Ubuntu24.04."""
import argparse
import json
import re
from pathlib import Path
from mongodb_security_source import refresh, source_review_inputs
from discover import fetch, resolve
ROOT = Path(__file__).resolve().parents[1]

def review_inputs(lock):
    # Tools minor changes require review; same tools100.x minor patch and server8.0
    # patches/base security refreshes may use the existing protected routine flow.
    result = {**lock, 'tools': {'release_line': '.'.join(lock['tools']['version'].split('.')[:2]), 'distribution': 'ubuntu2404'}, 'releases': [], 'security_source': source_review_inputs('mongodb')}
    for release in lock['releases']:
        version, major = release['mongodb_version'], release['major']
        if not re.fullmatch(re.escape(major) + r'\.\d+', version):
            raise ValueError('Patch must remain in reviewed stable server line')
        if not re.fullmatch(re.escape('docker.io/library/mongo:' + version + '-noble') + r'@sha256:[a-f0-9]{64}', release['base_image']):
            raise ValueError('Expected official MongoDB Noble fixture')
        if not re.fullmatch(r'docker.io/library/ubuntu:24\.04@sha256:[a-f0-9]{64}', release['backup_base_image']):
            raise ValueError('Expected Ubuntu24.04')
        result['releases'].append({k: v for k, v in release.items() if k not in {'mongodb_version', 'base_image', 'backup_base_image'}})
    return result

def discover(update_source=True):
    current = json.loads((ROOT / 'images/mongodb/versions.lock.json').read_text())
    metadata = json.loads((ROOT / 'images/mongodb/image.json').read_text())
    upstream = fetch('https://raw.githubusercontent.com/docker-library/official-images/master/library/mongo')[0].decode()
    available = json.loads(fetch('https://fastdl.mongodb.org/tools/db/release.json')[0])['versions']
    stable = [item for item in available if re.fullmatch(r'100\.\d+\.\d+', item['version'])]
    latest = max(stable, key=lambda item: tuple(map(int, item['version'].split('.'))))
    archives = {}
    for arch, source in [('amd64', 'x86_64'), ('arm64', 'arm64')]:
        matches = [d['archive'] for d in latest['downloads'] if d['name'] == 'ubuntu2404' and d['arch'] == source]
        if len(matches) != 1:
            raise ValueError('Exactly one supported official tools archive required for ' + arch)
        artifact = matches[0]
        expected = 'https://fastdl.mongodb.org/tools/db/mongodb-database-tools-ubuntu2404-' + source + '-' + latest['version'] + '.tgz'
        if artifact['url'] != expected or not re.fullmatch(r'[a-f0-9]{64}', artifact['sha256']):
            raise ValueError('Invalid tools download origin/checksum')
        archives[arch] = {key: artifact[key] for key in ['url', 'sha256']}
    base, platforms = resolve('24.04', repository='ubuntu')
    records = []
    for major in metadata['supported_majors']:
        versions = re.findall(r'(?<![\w.])(' + re.escape(major) + r'\.\d+)-noble(?=[,\s]|$)', upstream)
        if not versions:
            raise ValueError('Reviewed server release is unavailable')
        version = max(versions, key=lambda v: tuple(map(int, v.split('.'))))
        server, server_platforms = resolve(version + '-noble', repository='mongo')
        if platforms != server_platforms:
            raise ValueError('Both native architectures required')
        previous = next(item for item in current['releases'] if item['major'] == major)
        records.append({**previous, 'mongodb_version': version, 'base_image': server, 'backup_base_image': base, 'platforms': platforms})
    if update_source:
        refresh('mongodb', latest['version'])
    return {**current, 'tools': {'version': latest['version'], 'archives': archives}, 'releases': records}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--review-inputs', action='store_true')
    args = parser.parse_args()
    output = ROOT / 'images/mongodb/versions.lock.json'
    if args.review_inputs:
        print(json.dumps(review_inputs(json.loads(output.read_text())), sort_keys=True, separators=(',', ':')))
        return
    content = json.dumps(discover(update_source=not args.check), indent=2) + '\n'
    if args.check:
        if output.read_text() != content:
            raise SystemExit('MongoDB inputs changed; discover and qualify update')
    else:
        output.write_text(content)
        print(output.relative_to(ROOT))
if __name__ == '__main__':
    main()
