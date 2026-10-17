"""Refresh exact reviewed upstream source and checksum-locked Go module inputs."""
import hashlib,json,os,re,subprocess,tarfile,tempfile,io
from pathlib import Path
from discover import fetch,resolve
ROOT=Path(__file__).resolve().parents[1]
REPOSITORIES={'mongodb':('mongodb/mongo-tools',''), 'mongodb-exporter':('percona/mongodb_exporter','v')}
def source_review_inputs(product):
 source=json.loads((ROOT/'images'/product/'security-source.lock.json').read_text())
 return {key:value for key,value in source.items() if key not in {'upstream_version','upstream_commit','source_url','source_sha256','go'}} | {'go':{'release_line':'.'.join(source['go']['version'].split('.')[:2]),'distribution':'bookworm'}}
def refresh(product,version):
 repository,prefix=REPOSITORIES[product]
 directory=ROOT/'images'/product
 path=directory/'security-source.lock.json';source=json.loads(path.read_text())
 upstream=fetch('https://raw.githubusercontent.com/docker-library/official-images/master/library/golang')[0].decode()
 versions=re.findall(r'(?<![\w.])(1\.27\.\d+)-bookworm(?=[,\s]|$)',upstream)
 if not versions:raise ValueError('Reviewed compiler line unavailable')
 compiler=max(versions,key=lambda v:tuple(map(int,v.split('.'))));image,_=resolve(compiler+'-bookworm',repository='golang')
 source['go']={'version':compiler,'base_image':image}
 if source['upstream_version']!=version:
  obj=json.loads(fetch('https://api.github.com/repos/'+repository+'/git/ref/tags/'+prefix+version)[0])['object']
  if obj['type']=='tag':obj=json.loads(fetch('https://api.github.com/repos/'+repository+'/git/tags/'+obj['sha'])[0])['object']
  if obj['type']!='commit' or not re.fullmatch(r'[a-f0-9]{40}',obj['sha']):raise ValueError('Expected exact upstream release commit')
  commit=obj['sha'];url='https://github.com/'+repository+'/archive/'+commit+'.tar.gz';data=fetch(url)[0]
  with tempfile.TemporaryDirectory(prefix='mongodb-security-discovery-') as temporary:
   tree=Path(temporary)
   with tarfile.open(fileobj=io.BytesIO(data)) as archive:archive.extractall(tree,filter='data')
   roots=list(tree.iterdir())
   if len(roots)!=1 or not roots[0].is_dir():raise ValueError('Unexpected upstream archive structure')
   tree=roots[0];env={**os.environ,'GOTOOLCHAIN':'go'+compiler,'GOFLAGS':'-mod=mod'}
   requirements=json.loads(subprocess.check_output(['go','mod','edit','-json'],cwd=tree,env=env,text=True))['Require']
   current={x['Path']:x['Version'] for x in requirements}
   overrides=[]
   for module,floor in source['module_overrides'].items():
    installed=current.get(module,'v0.0.0')
    if not re.fullmatch(r'v\d+\.\d+\.\d+',installed):raise ValueError('Security dependency has an unreviewed version form')
    selected=max([floor,installed],key=lambda v:tuple(map(int,v[1:].split('.'))))
    overrides.append(module+'@'+selected)
   subprocess.run(['go','get',*overrides],cwd=tree,env=env,check=True)
   subprocess.run(['go','mod','download'],cwd=tree,env=env,check=True)
   subprocess.run(['go','mod','verify'],cwd=tree,env=env,check=True)
   for filename in ['go.mod','go.sum']:(directory/'security-build'/filename).write_bytes((tree/filename).read_bytes())
  source.update(upstream_version=version,upstream_commit=commit,source_url=url,source_sha256=hashlib.sha256(data).hexdigest())
 path.write_text(json.dumps(source,indent=2)+'\n')
