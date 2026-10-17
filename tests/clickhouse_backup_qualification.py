#!/usr/bin/env python3
"""Native generic client qualification: strict TLS, native archives and cancellation."""
import hashlib,json,os,pathlib,secrets,shutil,subprocess,sys,tempfile,time,uuid
import xml.etree.ElementTree as ET

backup,server=sys.argv[1:3]
identity='clickhouse-client-qual-'+uuid.uuid4().hex[:12]
network=identity+'-network'; server_name=identity+'-server'; owned=[]
private_root=pathlib.Path(tempfile.mkdtemp(prefix=identity+'-'));root=private_root/'mounted';root.mkdir(mode=0o755)
archive=private_root/'archives';archive.mkdir();archive.chmod(0o777)
password=secrets.token_urlsafe(24)
def command(*args,timeout=90,check=True):
 result=subprocess.run(list(args),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=timeout)
 if check and result.returncode:raise RuntimeError('command failed: '+args[0]+' '+args[1]+'; '+result.stderr[-1500:].replace(password,'[redacted]'))
 return result

def xml_config(host='ch-fixture',ca='/tls/ca.pem'):
 config=ET.Element('config')
 for key,value in {'host':host,'port':'9440','user':'default','password':password,'database':'default','secure':'true'}.items():ET.SubElement(config,key).text=value
 ssl=ET.SubElement(ET.SubElement(config,'openSSL'),'client');ET.SubElement(ssl,'caConfig').text=ca;ET.SubElement(ssl,'verificationMode').text='strict'
 return ET.tostring(config)

def client(sql,name=None,extra=(),config='connection.xml',timeout=60,check=True):
 args=['docker','run','--rm','--network',network,'--cap-drop=ALL','--security-opt=no-new-privileges','--read-only','--tmpfs','/tmp:rw,nosuid,nodev,noexec,size=16m',
 '--mount','type=bind,src='+str(root)+',dst=/tls,readonly','--mount','type=bind,src='+str(archive)+',dst=/backup']
 if name:args+=['--name',name];owned.append(name)
 args += [backup,'clickhouse-sql','--config-file=/tls/'+config,'--query',sql,*extra]
 return command(*args,timeout=timeout,check=check)

def query(sql,**kwargs):return client(sql,**kwargs).stdout.strip()

try:
 command('docker','network','create',network)
 # Test-only keys; the parent directory is private on the host.
 command('openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-keyout',str(root/'ca.key'),'-out',str(root/'ca.pem'),'-subj','/CN=fixture-ca')
 command('openssl','req','-newkey','rsa:2048','-nodes','-keyout',str(root/'server.key'),'-out',str(root/'server.csr'),'-subj','/CN=ch-fixture')
 (root/'extensions.cnf').write_text('subjectAltName=DNS:ch-fixture\nextendedKeyUsage=serverAuth\n')
 command('openssl','x509','-req','-in',str(root/'server.csr'),'-CA',str(root/'ca.pem'),'-CAkey',str(root/'ca.key'),'-CAcreateserial','-days','1','-out',str(root/'server.pem'),'-extfile',str(root/'extensions.cnf'))
 (root/'connection.xml').write_bytes(xml_config());(root/'wrong-host.xml').write_bytes(xml_config(host=server_name));(root/'wrong-ca.xml').write_bytes(xml_config(ca='/tls/server.pem'))
 (root/'server.xml').write_text("""<clickhouse><listen_host>0.0.0.0</listen_host><tcp_port_secure>9440</tcp_port_secure><max_server_memory_usage>1073741824</max_server_memory_usage><max_thread_pool_size>128</max_thread_pool_size><background_pool_size>16</background_pool_size><background_schedule_pool_size>4</background_schedule_pool_size><background_message_broker_schedule_pool_size>2</background_message_broker_schedule_pool_size><background_distributed_schedule_pool_size>2</background_distributed_schedule_pool_size><openSSL><server><certificateFile>/tls/server.pem</certificateFile><privateKeyFile>/tls/server.key</privateKeyFile><verificationMode>none</verificationMode></server></openSSL><storage_configuration><disks><backups><type>local</type><path>/backups/</path></backups></disks></storage_configuration><backups><allowed_disk>backups</allowed_disk></backups></clickhouse>""")
 (root/'users.xml').write_text('<clickhouse><users><default><password remove="1"/><password_sha256_hex>'+hashlib.sha256(password.encode()).hexdigest()+'</password_sha256_hex><networks><ip>::/0</ip></networks><profile>default</profile><quota>default</quota><access_management>1</access_management></default></users><profiles><default><max_threads>2</max_threads></default></profiles></clickhouse>')
 for file in root.iterdir():
  if file.is_file():file.chmod(0o444)
 command('docker','run','-d','--name',server_name,'--network',network,'--network-alias','ch-fixture','--memory','2g','--cpus','2',
 '--env','CLICKHOUSE_SKIP_USER_SETUP=1','--mount','type=bind,src='+str(root)+',dst=/tls,readonly',
 '--mount','type=bind,src='+str(root/'server.xml')+',dst=/etc/clickhouse-server/config.d/backup-fixture.xml,readonly',
 '--mount','type=bind,src='+str(root/'users.xml')+',dst=/etc/clickhouse-server/users.d/backup-fixture.xml,readonly',
 '--mount','type=bind,src='+str(archive)+',dst=/backups',server)
 deadline=time.monotonic()+120
 while True:
  try:
   observed=query('SELECT version() FORMAT TSVRaw',timeout=20);break
  except (RuntimeError,subprocess.TimeoutExpired):
   if time.monotonic()>deadline:
    logs=command('docker','logs','--tail','60',server_name,check=False)
    raise RuntimeError('server fixture failed readiness: '+(logs.stdout+logs.stderr)[-3000:].replace(password,'[redacted]'))
   time.sleep(2)
 expected=server.split(':')[-1].split('-jammy')[0]
 if observed!=expected:raise RuntimeError('wrong server fixture version: '+observed)
 version=command('docker','run','--rm',backup,'clickhouse-sql','--version').stdout.strip()
 if 'official clickhouse-go/v2 2.49.0' not in version:raise RuntimeError('unexpected driver version')
 if command('docker','run','--rm',backup,'id','-u').stdout.strip()!='10001':raise RuntimeError('client is not nonroot')
 if command('docker','run','--rm','--user','101:101',backup,'id','-u').stdout.strip()!='101':raise RuntimeError('explicit nonroot UID cannot start')
 command('docker','run','--rm',backup,'sh','-ec','! command -v clickhouse; ! command -v clickhouse-server; ! command -v gcc; test -x /bin/setpriv; test -x /sbin/tini')
 for config in ['wrong-host.xml','wrong-ca.xml']:
  if client('SELECT 1',config=config,check=False).returncode==0:raise RuntimeError('TLS identity/CA bypass accepted')
 query('CREATE TABLE default.fixture (id UInt64, payload String) ENGINE=MergeTree ORDER BY id')
 query("INSERT INTO default.fixture VALUES (1,'alpha'),(2,'βeta'),(3,'gamma')")
 if query('SELECT count(),sum(id) FROM default.fixture FORMAT TSVRaw')!='3\t6':raise RuntimeError('client query data mismatch')
 operation=str(uuid.uuid4())
 result=query("BACKUP DATABASE default TO Disk('backups','fixture.zip') SETTINGS id='"+operation+"'",extra=['--query_id='+operation,'--timeout=60s'],timeout=75)
 if 'BACKUP_CREATED' not in result:raise RuntimeError('native backup did not complete')
 command('docker','run','--rm','--mount','type=bind,src='+str(archive)+',dst=/backup,readonly',backup,'unzip','-t','/backup/fixture.zip')
 query('DROP TABLE default.fixture')
 query("RESTORE DATABASE default FROM Disk('backups','fixture.zip')",extra=['--timeout=60s'],timeout=75)
 if query('SELECT count(),sum(id),anyIf(payload,id=2) FROM default.fixture FORMAT TSVRaw')!='3\t6\tβeta':raise RuntimeError('native restore changed data')
 # Native context cancellation must stop an owned running query, not merely its CLI.
 cancel_id=str(uuid.uuid4());name=identity+'-cancel'
 args=['docker','run','--rm','--name',name,'--network',network,'--mount','type=bind,src='+str(root)+',dst=/tls,readonly',backup,'clickhouse-sql','--config-file=/tls/connection.xml','--query_id='+cancel_id,'--query','SELECT sleepEachRow(1) FROM numbers(30)']
 owned.append(name);process=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
 for _ in range(20):
  if query("SELECT count() FROM system.processes WHERE query_id='"+cancel_id+"' FORMAT TSVRaw")=='1':break
  if process.poll() is not None:raise RuntimeError('cancel query exited before running')
  time.sleep(.5)
 else:raise RuntimeError('owned query never became observable')
 command('docker','kill','--signal','TERM',name)
 process.communicate(timeout=20)
 if process.returncode==0:raise RuntimeError('cancelled client reported success')
 for _ in range(20):
  if query("SELECT count() FROM system.processes WHERE query_id='"+cancel_id+"' FORMAT TSVRaw")=='0':break
  time.sleep(.5)
 else:raise RuntimeError('cancelled native query remained active')
 receipt={'server_version':observed,'client':version,'native_backup_restore':True,'tls_peer_and_ca_verified':True,'native_query_cancellation':True,'client_uid':10001,'server_binary_absent':True,'cleanup':True}
finally:
 for name in [*owned,server_name]:command('docker','rm','-f',name,check=False)
 command('docker','network','rm',network,check=False)
 # Container files may be owned by UID101 on native Linux.
 if archive.exists():command('docker','run','--rm','--user','0:0','--mount','type=bind,src='+str(archive)+',dst=/owned',backup,'sh','-ec','find /owned -mindepth 1 -delete',check=False)
 shutil.rmtree(private_root,ignore_errors=True)
 for name in [*owned,server_name]:
  if command('docker','inspect',name,check=False).returncode==0:raise RuntimeError('owned container cleanup failed')
 if command('docker','network','inspect',network,check=False).returncode==0:raise RuntimeError('owned network cleanup failed')
 if private_root.exists():raise RuntimeError('owned fixture file cleanup failed')
print(json.dumps(receipt,sort_keys=True))
