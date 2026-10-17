#!/usr/bin/env python3
"""Render a generic unchanged Percona exporter plus portable BusyBox runtime."""
import argparse,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
IMAGE=ROOT/'images/mongodb-exporter'
def rendered_files():
 metadata=json.loads((IMAGE/'image.json').read_text());lock=json.loads((IMAGE/'versions.lock.json').read_text())
 if metadata['targets']!=['runtime'] or metadata['variants']!=['busybox']:raise ValueError('Only reviewed exporter runtime supported')
 source=json.loads((IMAGE/'security-source.lock.json').read_text())
 if source['module_overrides']!={'golang.org/x/crypto':'v0.57.0','golang.org/x/mod':'v0.41.0','golang.org/x/net':'v0.60.0','google.golang.org/grpc':'v1.83.2'} or source['cgo_enabled'] or source['build_tags']!=[]:raise ValueError('Exporter security source contract requires review')
 if not re.fullmatch(r'[a-f0-9]{40}',source['upstream_commit']) or source['source_url']!='https://github.com/percona/mongodb_exporter/archive/'+source['upstream_commit']+'.tar.gz' or not re.fullmatch(r'[a-f0-9]{64}',source['source_sha256']):raise ValueError('Unpinned exporter source')
 if not re.fullmatch(r'1\.27\.\d+',source['go']['version']) or not re.fullmatch(re.escape('docker.io/library/golang:'+source['go']['version']+'-bookworm')+r'@sha256:[a-f0-9]{64}',source['go']['base_image']):raise ValueError('Expected pinned Go1.27Bookworm')
 seen=set()
 for item in lock['releases']:
  major=item['major'];version=item['mongodb-exporter_version']
  if source['upstream_version']!=version:raise ValueError('Reviewed security source must match exporter feature version')
  if major not in metadata['supported_majors'] or major in seen or item['release_line']!=major or item['variant']!='busybox':raise ValueError('Unexpected exporter release')
  seen.add(major)
  if not re.fullmatch(re.escape(major)+r'\.\d+',version):raise ValueError('Version must remain in reviewed exporter line')
  if not re.fullmatch(re.escape('docker.io/percona/mongodb_exporter:'+version)+r'@sha256:[a-f0-9]{64}',item['base_image']):raise ValueError('Expected pinned original Percona image')
  if not re.fullmatch(r'docker.io/library/busybox:1\.37\.\d+-uclibc@sha256:[a-f0-9]{64}',item['runtime_base_image']):raise ValueError('Expected pinned official BusyBoxuclibc')
  if item['platforms']!=['linux/amd64','linux/arm64']:raise ValueError('Both native architectures required')
  text=(IMAGE/'templates/Dockerfile.busybox').read_text()
  for token,value in {'GO_IMAGE':source['go']['base_image'],'SOURCE_URL':source['source_url'],'SOURCE_SHA256':source['source_sha256'],'UPSTREAM_COMMIT':source['upstream_commit'],'RUNTIME_BASE_IMAGE':item['runtime_base_image'],'EXPORTER_VERSION':version}.items():text=text.replace('{{'+token+'}}',value)
  yield IMAGE/'generated'/major/'busybox'/'Dockerfile',text
 if seen!=set(metadata['supported_majors']):raise ValueError('Missing exporter release')
def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--check',action='store_true');args=parser.parse_args();changed=[];expected=dict(rendered_files())
 for path,text in expected.items():
  if not path.exists() or path.read_text()!=text:
   changed.append(str(path.relative_to(ROOT)))
   if not args.check:path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
 for path in (IMAGE/'generated').rglob('Dockerfile*'):
  if path not in expected:
   changed.append(str(path.relative_to(ROOT)))
   if not args.check:path.unlink()
 if args.check and changed:raise SystemExit('Generated recipes differ: '+', '.join(changed))
 print(('Checked' if args.check else 'Generated')+' '+str(len(expected))+' Dockerfiles')
if __name__=='__main__':main()
