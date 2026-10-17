#!/usr/bin/env python3
"""Render the reviewed genuine client-only ClickHouse image."""
import argparse,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
IMAGE=ROOT/'images/clickhouse'
def rendered_files():
 metadata=json.loads((IMAGE/'image.json').read_text()); lock=json.loads((IMAGE/'versions.lock.json').read_text())
 if metadata['targets']!=['backup'] or metadata['variants']!=['alpine3.22']: raise ValueError('Only the reviewed Alpine backup target is supported')
 if lock['client']!={'name':'clickhouse-sql','version':'1.0.0','driver':'github.com/ClickHouse/clickhouse-go/v2','driver_version':'2.49.0'}: raise ValueError('Client/driver changes require explicit review')
 compiler=lock['go']; version=compiler['version']
 if not re.fullmatch(r'1\.27\.\d+',version) or not re.fullmatch(re.escape('docker.io/library/golang:'+version+'-bookworm')+r'@sha256:[a-f0-9]{64}',compiler['base_image']): raise ValueError('Compiler must remain pinned official Go1.27 Bookworm')
 seen=set()
 for release in lock['releases']:
  major,variant,version=release['major'],release['variant'],release['clickhouse_version']
  if (major,variant) in seen or major not in metadata['supported_majors'] or variant!='alpine3.22': raise ValueError('Unexpected release')
  seen.add((major,variant))
  if not re.fullmatch(re.escape(major)+r'\.\d+\.\d+',version) or release['release_line']!=major: raise ValueError('Version must stay in reviewed LTS line')
  for key,pattern in [('base_image',re.escape('docker.io/library/clickhouse:'+version+'-jammy')+r'@sha256:[a-f0-9]{64}'),('backup_base_image',r'docker.io/library/alpine:3\.22@sha256:[a-f0-9]{64}')]:
   if not re.fullmatch(pattern,release[key]): raise ValueError('Unpinned or unexpected official image')
  if release['platforms']!=['linux/amd64','linux/arm64']: raise ValueError('Both native architectures required')
  text=(IMAGE/'templates/Dockerfile.backup.alpine3.22').read_text()
  for token,value in {'GO_IMAGE':compiler['base_image'],'BACKUP_BASE_IMAGE':release['backup_base_image'],'CLICKHOUSE_VERSION':version,'DRIVER_VERSION':lock['client']['driver_version']}.items(): text=text.replace('{{'+token+'}}',value)
  if re.search(r'\{\{[A-Z_]+\}\}',text): raise ValueError('Unresolved template token')
  yield IMAGE/'generated'/major/variant/'Dockerfile.backup',text
 if seen!={(m,'alpine3.22') for m in metadata['supported_majors']}: raise ValueError('Missing reviewed release')
def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--check',action='store_true');args=parser.parse_args();changed=[]
 expected=dict(rendered_files())
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
