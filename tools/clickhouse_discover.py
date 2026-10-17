#!/usr/bin/env python3
"""Resolve official ClickHouse LTS patches and pinned build/base updates."""
import argparse,json,re
from pathlib import Path
from discover import fetch,resolve
ROOT=Path(__file__).resolve().parents[1]
def review_inputs(lock):
 result={**lock,'go':{'release_line':'.'.join(lock['go']['version'].split('.')[:2]),'distribution':'bookworm'},'releases':[]}
 for release in lock['releases']:
  version=release['clickhouse_version'];major=release['major']
  if not re.fullmatch(re.escape(major)+r'\.\d+\.\d+',version):raise ValueError('Patch must remain in reviewed LTS line')
  if not re.fullmatch(re.escape('docker.io/library/clickhouse:'+version+'-jammy')+r'@sha256:[a-f0-9]{64}',release['base_image']):raise ValueError('Expected official ClickHouse Jammy fixture')
  if not re.fullmatch(r'docker.io/library/alpine:3\.22@sha256:[a-f0-9]{64}',release['backup_base_image']):raise ValueError('Expected Alpine3.22')
  result['releases'].append({k:v for k,v in release.items() if k not in {'clickhouse_version','base_image','backup_base_image'}})
 return result

def discover():
 current=json.loads((ROOT/'images/clickhouse/versions.lock.json').read_text());metadata=json.loads((ROOT/'images/clickhouse/image.json').read_text())
 upstream=fetch('https://raw.githubusercontent.com/docker-library/official-images/master/library/clickhouse')[0].decode()
 go_upstream=fetch('https://raw.githubusercontent.com/docker-library/official-images/master/library/golang')[0].decode()
 compiler=max(re.findall(r'(?<![\w.])(1\.27\.\d+)-bookworm(?=[,\s]|$)',go_upstream),key=lambda v:tuple(map(int,v.split('.'))))
 compiler_image,_=resolve(compiler+'-bookworm',repository='golang');base,platforms=resolve('3.22',repository='alpine');records=[]
 for major in metadata['supported_majors']:
  versions=re.findall(r'(?<![\w.])('+re.escape(major)+r'\.\d+\.\d+)-jammy(?=[,\s]|$)',upstream)
  if not versions:raise ValueError('Reviewed LTS release is unavailable')
  version=max(versions,key=lambda v:tuple(map(int,v.split('.'))));server,server_platforms=resolve(version+'-jammy',repository='clickhouse')
  if platforms!=server_platforms:raise ValueError('Both native architectures required')
  previous=next(item for item in current['releases'] if item['major']==major)
  records.append({**previous,'clickhouse_version':version,'base_image':server,'backup_base_image':base,'platforms':platforms})
 return {**current,'go':{'version':compiler,'base_image':compiler_image},'releases':records}

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--check',action='store_true');parser.add_argument('--review-inputs',action='store_true');args=parser.parse_args();output=ROOT/'images/clickhouse/versions.lock.json'
 if args.review_inputs: print(json.dumps(review_inputs(json.loads(output.read_text())),sort_keys=True,separators=(',',':')));return
 content=json.dumps(discover(),indent=2)+'\n'
 if args.check:
  if output.read_text()!=content:raise SystemExit('ClickHouse inputs changed; discover and qualify update')
 else:output.write_text(content);print(output.relative_to(ROOT))
if __name__=='__main__':main()
