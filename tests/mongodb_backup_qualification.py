#!/usr/bin/env python3
"""Native authenticated replica-set archive/replay and client-only qualification."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time

BACKUP, RUNTIME = sys.argv[1:3]
PREFIX = 'mongodb-image-' + secrets.token_hex(6)
NETWORK = PREFIX + '-network'
VOLUMES = [PREFIX + '-source', PREFIX + '-restore', PREFIX + '-archive']
CONTAINERS = [PREFIX + '-source', PREFIX + '-restore', PREFIX + '-cancel']
PASSWORD = secrets.token_hex(24)

def docker(*args, check=True, timeout=180):
    result = subprocess.run(['docker', *args], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if check and result.returncode:
        # Do not echo command arguments, credentials or tool output in CI.
        raise RuntimeError('Docker qualification operation failed: ' + args[0] + ', exit=' + str(result.returncode))
    return result

def client(directory, *args, check=True, name=None):
    command = ['run', '--rm', '--network', NETWORK, '-v', str(directory) + ':/fixture:ro', '-v', VOLUMES[2] + ':/backup']
    if name:
        command += ['--name', name]
    return docker(*command, BACKUP, *args, check=check)

def js(server, source, directory):
    path = directory / 'setup.js'
    path.write_text(source)
    return docker('exec', server, 'mongosh', '--quiet', '--file', '/fixture/setup.js')

with tempfile.TemporaryDirectory(prefix=PREFIX) as temporary:
    directory = Path(temporary)
    directory.chmod(0o755)  # Disposable random fixture; credentials removed in finally.
    try:
        docker('network', 'create', NETWORK)
        for volume in VOLUMES:
            docker('volume', 'create', volume)
        metadata = json.loads(docker('image', 'inspect', BACKUP).stdout)[0]['Config']
        assert metadata['User'] == '10001:10001'
        client(directory, 'sh', '-ec', 'test "$(id -u)" = 10001; ! command -v mongod; ! command -v mongos; ! command -v mongosh; mongodump --version; mongorestore --version; bsondump --version; python3 -c "import pymongo, yaml"')
        docker('run', '--rm', '--user', '0:0', '-v', VOLUMES[2] + ':/backup', '--entrypoint', '/bin/sh', BACKUP, '-ec', 'chown 10001:10001 /backup; chmod 0700 /backup')
        for server, volume in zip(CONTAINERS[:2], VOLUMES[:2]):
            # Initialize the fixture-only internal replica key using server volume.
            docker('run', '--rm', '--user', '0:0', '-v', volume + ':/data/db', '--entrypoint', '/bin/sh', BACKUP, '-ec', 'umask 077; head -c 64 /dev/urandom | base64 > /data/db/key; chown 999:999 /data/db/key; chmod 0400 /data/db/key')
            docker('run', '-d', '--name', server, '--network', NETWORK, '-v', volume + ':/data/db', '-v', str(directory) + ':/fixture:ro', '--tmpfs', '/data/configdb:rw,size=8388608,mode=0700', RUNTIME, '--replSet', 'fixture', '--bind_ip_all', '--auth', '--keyFile', '/data/db/key')
            for _ in range(90):
                if docker('exec', server, 'mongosh', '--quiet', '--eval', 'db.adminCommand({ping:1}).ok', check=False).returncode == 0:
                    break
                time.sleep(1)
            else:
                raise RuntimeError('Server fixture startup timed out')
            js(server, 'rs.initiate({_id:"fixture",members:[{_id:0,host:' + json.dumps(server + ':27017') + '}]});', directory)
            for _ in range(60):
                result = docker('exec', server, 'mongosh', '--quiet', '--eval', 'if (!db.hello().isWritablePrimary) quit(2)', check=False)
                if result.returncode == 0:
                    break
                time.sleep(1)
            else:
                raise RuntimeError('Replica-set election timed out')
            js(server, 'db.getSiblingDB("admin").createUser({user:"fixture_admin",pwd:' + json.dumps(PASSWORD) + ',roles:["root"]});', directory)
        source, restore = CONTAINERS[:2]
        config = {'uri': 'mongodb://fixture_admin@' + source + ':27017/?authSource=admin&directConnection=true', 'password': PASSWORD}
        (directory / 'dump.yml').write_text(json.dumps(config))
        (directory / 'restore.yml').write_text(json.dumps({**config, 'uri': 'mongodb://fixture_admin@' + restore + ':27017/?authSource=admin&directConnection=true'}))
        (directory / 'admin.json').write_text(json.dumps({'source': source, 'restore': restore, 'password': PASSWORD}))
        script = '''import json, pymongo
from bson import ObjectId, Binary, Decimal128
c=json.load(open('/fixture/admin.json'))
def connect(host): return pymongo.MongoClient(host, username='fixture_admin',password=c['password'],authSource='admin',directConnection=True,serverSelectionTimeoutMS=5000)
a=connect(c['source']); a.fixture.items.insert_many([{'_id':ObjectId(),'unicode':'سلام 🌍','binary':Binary(b'\\x00\\xff'),'decimal':Decimal128('1234.50'),'n':n} for n in range(3)]); a.fixture.items.create_index('n',unique=True); a.fixture.command({'create':'view','viewOn':'items','pipeline':[{'$match':{'n':{'$gte':1}}}]}); assert a.fixture.items.count_documents({})==3
'''
        (directory / 'prepare.py').write_text(script)
        client(directory, 'python3', '/fixture/prepare.py')
        client(directory, 'mongodump', '--config=/fixture/dump.yml', '--archive=/backup/database.archive.gz', '--gzip', '--oplog')
        # Archive is nonempty and is private under the default unprivileged user.
        client(directory, 'sh', '-ec', 'test -s /backup/database.archive.gz; test "$(stat -c %a /backup/database.archive.gz)" = 600')
        client(directory, 'mongorestore', '--config=/fixture/restore.yml', '--archive=/backup/database.archive.gz', '--gzip', '--oplogReplay', '--drop')
        (directory / 'verify.py').write_text('''import json,pymongo
from bson import Binary, Decimal128
c=json.load(open('/fixture/admin.json')); a=pymongo.MongoClient(c['restore'],username='fixture_admin',password=c['password'],authSource='admin',directConnection=True,serverSelectionTimeoutMS=5000)
rows=list(a.fixture.items.find().sort('n')); assert len(rows)==3 and [r['n'] for r in rows]==[0,1,2]; assert rows[0]['unicode']=='سلام 🌍' and rows[0]['binary']==b'\\x00\\xff' and rows[0]['decimal']==Decimal128('1234.50'); assert a.fixture.view.count_documents({})==2; assert any(x.get('unique') and dict(x['key'])=={'n':1} for x in a.fixture.items.list_indexes())
''')
        client(directory, 'python3', '/fixture/verify.py')
        docker('restart', restore)
        for _ in range(60):
            if client(directory, 'python3', '/fixture/verify.py', check=False).returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError('Restored fixture did not survive restart')
        (directory / 'wrong.yml').write_text(json.dumps({**config, 'password': 'intentionally-wrong'}))
        assert client(directory, 'mongodump', '--config=/fixture/wrong.yml', '--archive=/backup/invalid.archive', '--gzip', '--oplog', check=False).returncode != 0
        client(directory, 'sh', '-ec', 'printf corrupt > /backup/corrupt.archive.gz')
        assert client(directory, 'mongorestore', '--config=/fixture/restore.yml', '--archive=/backup/corrupt.archive.gz', '--gzip', '--oplogReplay', check=False).returncode != 0
        # Terminate the actual client blocked awaiting a server handshake, not a surrogate sleep.
        blackhole = subprocess.Popen(['docker','run','--rm','--name',CONTAINERS[2],'--network',NETWORK,BACKUP,'mongodump','--host=192.0.2.1:27017','--archive=/tmp/never.archive'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        time.sleep(2)
        docker('kill', '--signal=TERM', CONTAINERS[2])
        assert blackhole.wait(timeout=15) != 0
        print(json.dumps({'engine':'mongodb','toolsVersion':'100.19.1','authenticatedReplicaSet':True,'archiveGzipOplogReplay':True,'freshRestoreBsonIndexesViews':True,'restart':True,'wrongPasswordRejected':True,'corruptArchiveRejected':True,'clientSignalCancellation':True,'clientOnlyNonRoot':True}))
    finally:
        for name in CONTAINERS:
            docker('rm','-fv',name,check=False)
        for volume in VOLUMES:
            docker('volume','rm',volume,check=False)
        docker('network','rm',NETWORK,check=False)
