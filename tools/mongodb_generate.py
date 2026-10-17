#!/usr/bin/env python3
"""Render the reviewed genuine client-only MongoDB backup image."""
import argparse
import json
import re
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
IMAGE = ROOT / 'images/mongodb'

def rendered_files():
    metadata = json.loads((IMAGE / 'image.json').read_text())
    lock = json.loads((IMAGE / 'versions.lock.json').read_text())
    if metadata['targets'] != ['backup'] or metadata['variants'] != ['noble']:
        raise ValueError('Only the reviewed Ubuntu24.04 backup target is supported')
    tools = lock['tools']
    if not re.fullmatch(r'100\.\d+\.\d+', tools['version']):
        raise ValueError('Expected stable independently versioned Database Tools100.x')
    if set(tools['archives']) != {'amd64', 'arm64'}:
        raise ValueError('Both tools architectures required')
    for arch, upstream in [('amd64', 'x86_64'), ('arm64', 'arm64')]:
        artifact = tools['archives'][arch]
        expected = 'https://fastdl.mongodb.org/tools/db/mongodb-database-tools-ubuntu2404-' + upstream + '-' + tools['version'] + '.tgz'
        if artifact['url'] != expected or not re.fullmatch(r'[a-f0-9]{64}', artifact['sha256']):
            raise ValueError('Unexpected or unpinned official tools artifact')
    source = json.loads((IMAGE / 'security-source.lock.json').read_text())
    if source['upstream_version'] != tools['version'] or source['module_overrides'] != {'golang.org/x/net': 'v0.60.0'} or source['build_tags'] != ['gssapi', 'failpoints'] or not source['cgo_enabled'] or source['buildmode'] != 'pie':
        raise ValueError('Security rebuild source or feature contract requires review')
    if not re.fullmatch(r'[a-f0-9]{40}', source['upstream_commit']) or source['source_url'] != 'https://github.com/mongodb/mongo-tools/archive/' + source['upstream_commit'] + '.tar.gz' or not re.fullmatch(r'[a-f0-9]{64}', source['source_sha256']):
        raise ValueError('Unpinned official tools source')
    if not re.fullmatch(r'1\.27\.\d+', source['go']['version']) or not re.fullmatch(re.escape('docker.io/library/golang:' + source['go']['version'] + '-bookworm') + r'@sha256:[a-f0-9]{64}', source['go']['base_image']):
        raise ValueError('Expected pinned Go1.27 Bookworm')
    seen = set()
    for release in lock['releases']:
        major, variant, version = release['major'], release['variant'], release['mongodb_version']
        if (major, variant) in seen or major not in metadata['supported_majors'] or variant != 'noble':
            raise ValueError('Unexpected release')
        seen.add((major, variant))
        if not re.fullmatch(re.escape(major) + r'\.\d+', version) or release['release_line'] != major:
            raise ValueError('Version must stay in reviewed stable server line')
        for key, pattern in [('base_image', re.escape('docker.io/library/mongo:' + version + '-noble') + r'@sha256:[a-f0-9]{64}'), ('backup_base_image', r'docker.io/library/ubuntu:24\.04@sha256:[a-f0-9]{64}')]:
            if not re.fullmatch(pattern, release[key]):
                raise ValueError('Unpinned or unexpected official image')
        if release['platforms'] != ['linux/amd64', 'linux/arm64']:
            raise ValueError('Both native architectures required')
        text = (IMAGE / 'templates/Dockerfile.backup.noble').read_text()
        values = {'GO_IMAGE': source['go']['base_image'], 'SOURCE_URL': source['source_url'], 'SOURCE_SHA256': source['source_sha256'], 'UPSTREAM_COMMIT': source['upstream_commit'], 'BACKUP_BASE_IMAGE': release['backup_base_image'], 'MONGODB_VERSION': version, 'TOOLS_VERSION': tools['version']}
        for arch in ['amd64', 'arm64']:
            values[arch.upper() + '_URL'] = tools['archives'][arch]['url']
            values[arch.upper() + '_SHA256'] = tools['archives'][arch]['sha256']
        for token, value in values.items():
            text = text.replace('{{' + token + '}}', value)
        if re.search(r'\{\{[A-Z_]+\}\}', text):
            raise ValueError('Unresolved template token')
        yield IMAGE / 'generated' / major / variant / 'Dockerfile.backup', text
    if seen != {(m, 'noble') for m in metadata['supported_majors']}:
        raise ValueError('Missing reviewed release')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    expected = dict(rendered_files())
    changed = []
    for path, text in expected.items():
        if not path.exists() or path.read_text() != text:
            changed.append(str(path.relative_to(ROOT)))
            if not args.check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
    for path in (IMAGE / 'generated').rglob('Dockerfile*'):
        if path not in expected:
            changed.append(str(path.relative_to(ROOT)))
            if not args.check:
                path.unlink()
    if args.check and changed:
        raise SystemExit('Generated recipes differ: ' + ', '.join(changed))
    print(('Checked' if args.check else 'Generated') + ' ' + str(len(expected)) + ' Dockerfiles')
if __name__ == '__main__':
    main()
