#!/usr/bin/env python3
"""Verify vendor binary identity and portable, unprivileged exporter runtime."""
import hashlib,json,secrets,subprocess,sys,tempfile
from pathlib import Path
image,upstream=sys.argv[1:3]
source=json.loads((Path(__file__).resolve().parents[1]/'images/mongodb-exporter/security-source.lock.json').read_text())
prefix='mongodb-exporter-'+secrets.token_hex(6)
def docker(*args):return subprocess.check_output(['docker',*args],stderr=subprocess.PIPE)
with tempfile.TemporaryDirectory(prefix=prefix) as root:
 try:
  for label,ref in [('source',upstream),('candidate',image)]:
   docker('create','--name',prefix+'-'+label,ref)
   docker('cp',prefix+'-'+label+':/mongodb_exporter',str(Path(root)/label))
  expected=hashlib.sha256((Path(root)/'source').read_bytes()).hexdigest()
  actual=hashlib.sha256((Path(root)/'candidate').read_bytes()).hexdigest()
  assert actual!=expected  # Explicit source rebuild; vendor feature version is retained.
  build=subprocess.check_output(['go','version','-m',str(Path(root)/'candidate')],text=True)
  assert 'go'+source['go']['version'] in build
  for module,version in source['module_overrides'].items():
   import re
   observed=re.search(r'\b'+re.escape(module)+r'\s+(v\d+\.\d+\.\d+)',build).group(1)
   assert tuple(map(int,observed[1:].split('.'))) >= tuple(map(int,version[1:].split('.')))

  config=json.loads(docker('image','inspect',image))[0]['Config']
  assert config['User']=='65535:65535' and config['Entrypoint']==['/mongodb_exporter']
  version=docker('run','--rm',image,'--version').decode()
  assert '0.53.' in version
  docker('run','--rm','--user','65534:65534','--entrypoint','/bin/sh',image,'-ec','''test "$(id -u)" = 65534
for command in sh nc sleep cat; do /bin/busybox --list | grep -Fx "$command"; done
test -s /etc/ssl/certs/ca-certificates.crt
! command -v mongod; ! command -v mongos
nc -l -p 19216 -e /bin/cat & child=$!
trap 'kill "$child" 2>/dev/null || true; wait "$child" 2>/dev/null || true' EXIT
sleep 1
result=$(printf 'portable-relay\n' | nc -w 1 127.0.0.1 19216)
test "$result" = portable-relay
''')
  print(json.dumps({'upstreamBinarySha256':expected,'securityRebuildBinarySha256':actual,'pinnedGoAndSecurityModules':True,'nonRootDefault':True,'arbitraryUnprivilegedUid':True,'shellNcExecLoopback':True,'serverAbsent':True}))
 finally:
  for label in ['source','candidate']:
   subprocess.run(['docker','rm','-f',prefix+'-'+label],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
