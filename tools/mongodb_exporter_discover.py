#!/usr/bin/env python3
"""Resolve reviewed Percona exporter patches and BusyBox security refreshes."""
import argparse, hashlib, json, re
from pathlib import Path
from discover import ACCEPT, fetch, resolve
ROOT=Path(__file__).resolve().parents[1]
def resolve_percona(version):
 repository='percona/mongodb_exporter'
 token=json.loads(fetch('https://auth.docker.io/token?service=registry.docker.io&scope=repository:'+repository+':pull')[0])['token']
 raw,headers=fetch('https://registry-1.docker.io/v2/'+repository+'/manifests/'+version,{'Authorization':'Bearer '+token,'Accept':ACCEPT})
 digest='sha256:'+hashlib.sha256(raw).hexdigest()
 if headers.get('Docker-Content-Digest')!=digest:raise ValueError('Percona registry digest mismatch')
 platforms={'linux/'+x.get('platform',{}).get('architecture','') for x in json.loads(raw).get('manifests',[]) if x.get('platform',{}).get('os')=='linux'}
 if not {'linux/amd64','linux/arm64'}<=platforms:raise ValueError('Both native exporter architectures required')
 return 'docker.io/'+repository+':'+version+'@'+digest

def review_inputs(lock):
 result={**lock,'releases':[]}
 for item in lock['releases']:
  version=item['mongodb-exporter_version'];major=item['major']
  if not re.fullmatch(re.escape(major)+r'\.\d+',version):raise ValueError('Unreviewed exporter version')
  if not re.fullmatch(re.escape('docker.io/percona/mongodb_exporter:'+version)+r'@sha256:[a-f0-9]{64}',item['base_image']):raise ValueError('Expected pinned Percona image')
  if not re.fullmatch(r'docker.io/library/busybox:1\.37\.\d+-uclibc@sha256:[a-f0-9]{64}',item['runtime_base_image']):raise ValueError('Expected reviewed BusyBox line')
  result['releases'].append({k:v for k,v in item.items() if k not in {'mongodb-exporter_version','base_image','runtime_base_image'}})
 return result

def discover():
 current=json.loads((ROOT/'images/mongodb-exporter/versions.lock.json').read_text())
 tags=json.loads(fetch('https://api.github.com/repos/percona/mongodb_exporter/tags?per_page=100')[0])
 upstream=fetch('https://raw.githubusercontent.com/docker-library/official-images/master/library/busybox')[0].decode()
 variants=re.findall(r'(?<![\w.])(1\.37\.\d+)-uclibc(?=[,\s]|$)',upstream)
 if not variants:raise ValueError('Reviewed BusyBox line unavailable')
 base,_=resolve(max(variants,key=lambda v:tuple(map(int,v.split('.'))))+'-uclibc',repository='busybox')
 records=[]
 for item in current['releases']:
  versions=[x['name'][1:] for x in tags if re.fullmatch('v'+re.escape(item['major'])+r'\.\d+',x['name'])]
  if not versions:raise ValueError('Reviewed exporter line unavailable')
  version=max(versions,key=lambda v:tuple(map(int,v.split('.'))))
  records.append({**item,'mongodb-exporter_version':version,'base_image':resolve_percona(version),'runtime_base_image':base})
 return {**current,'releases':records}
def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--check',action='store_true');parser.add_argument('--review-inputs',action='store_true');args=parser.parse_args();output=ROOT/'images/mongodb-exporter/versions.lock.json'
 if args.review_inputs:print(json.dumps(review_inputs(json.loads(output.read_text())),sort_keys=True,separators=(',',':')));return
 content=json.dumps(discover(),indent=2)+'\n'
 if args.check:
  if output.read_text()!=content:raise SystemExit('Exporter inputs changed; discover and qualify update')
 else:output.write_text(content);print(output.relative_to(ROOT))
if __name__=='__main__':main()
