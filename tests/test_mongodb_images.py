import copy,json,sys,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import mongodb_generate,mongodb_discover,mongodb_exporter_generate,mongodb_exporter_discover,release
class MongoDBImagesTests(unittest.TestCase):
 def test_generated_backup_is_client_only_and_exact_tools(self):
  generated=dict(mongodb_generate.rendered_files());self.assertEqual(len(generated),1)
  for path,text in generated.items():
   self.assertEqual(path.read_text(),text)
   for contract in ['sha256sum --check --strict',"-buildmode=pie -tags 'gssapi failpoints'",'USER 10001:10001','python3-pymongo','python3-yaml','tini','setpriv','apt-get upgrade -y']:
    self.assertIn(contract,text)
   self.assertNotIn('COPY --from=tools /tmp/tools/bin/',text)
   self.assertIn('! command -v mongod',text)
 def test_tools_download_origin_and_checksums_are_validated(self):
  lock=json.loads((ROOT/'images/mongodb/versions.lock.json').read_text());lock['tools']['archives']['arm64']['url']='https://evil.invalid/tools.tgz'
  original=Path.read_text
  with patch.object(Path,'read_text',lambda path,*a,**k:json.dumps(lock) if path.name=='versions.lock.json' else original(path,*a,**k)):
   with self.assertRaisesRegex(ValueError,'official tools artifact'):list(mongodb_generate.rendered_files())
 def test_tags_and_targets(self):
  self.assertEqual(set(release.tags('8.0','noble','backup','mongodb')),{'abruncloud/mongodb:8.0.34-backup','abruncloud/mongodb:8.0-backup','abruncloud/mongodb:8.0.34-noble-backup','abruncloud/mongodb:8.0-noble-backup'})
  with self.assertRaises(ValueError):release.tags('8.0','noble','runtime','mongodb')
  self.assertEqual(set(release.tags('0.53','busybox','runtime','mongodb-exporter')),{'abruncloud/mongodb-exporter:0.53.0','abruncloud/mongodb-exporter:0.53','abruncloud/mongodb-exporter:0.53.0-busybox','abruncloud/mongodb-exporter:0.53-busybox'})
  with self.assertRaises(ValueError):release.tags('0.53','busybox','backup','mongodb-exporter')
 def test_both_native_architectures_and_correct_target(self):
  for image,target in [('mongodb','backup'),('mongodb-exporter','runtime')]:
   rows=release.matrix(target,image)['include'];self.assertEqual({r['arch'] for r in rows},{'amd64','arm64'})
   self.assertTrue(all(r['backup']==(target=='backup') for r in rows))
 def test_exporter_keeps_vendor_binary_and_nonroot_generic_entrypoint(self):
  for path,text in mongodb_exporter_generate.rendered_files():
   self.assertEqual(path.read_text(),text)
   self.assertIn('COPY --from=build /out/mongodb_exporter /mongodb_exporter',text)
   self.assertIn('go mod verify',text)
   self.assertIn('/etc/ssl/certs/ca-certificates.crt',text)
   self.assertIn('USER 65535:65535',text)
   self.assertIn('ENTRYPOINT ["/mongodb_exporter"]',text)
   self.assertIn('CGO_ENABLED=0 go build',text)
   self.assertNotIn('bootstrap',text)
 def test_routine_updates_have_reviewed_boundaries(self):
  lock=json.loads((ROOT/'images/mongodb/versions.lock.json').read_text());before=mongodb_discover.review_inputs(lock);updated=copy.deepcopy(lock)
  updated['tools']['version']='100.19.2';updated['tools']['archives']['amd64']['sha256']='a'*64
  item=updated['releases'][0];item['mongodb_version']='8.0.35';item['base_image']='docker.io/library/mongo:8.0.35-noble@sha256:'+'a'*64
  self.assertEqual(before,mongodb_discover.review_inputs(updated))
  updated['tools']['version']='100.20.0';self.assertNotEqual(before,mongodb_discover.review_inputs(updated))
  item['mongodb_version']='8.2.0'
  with self.assertRaises(ValueError):mongodb_discover.review_inputs(updated)
 def test_native_security_and_required_ci(self):
  check=(ROOT/'.github/workflows/check.yml').read_text()
  for job in ['mongodb-native-test','mongodb-exporter-native-test']:self.assertIn(job,check)
  for product,script in [('mongodb','run-mongodb-backup.sh'),('mongodb-exporter','run-mongodb-exporter.sh')]:
   workflow=(ROOT/'.github/workflows'/f'{product}-release.yml').read_text()
   for contract in [script,'TRIVY_PLATFORM: linux/${{ matrix.arch }}','Scanner architecture mismatch','sbom: true','provenance: mode=max','needs: [metadata, qualify]',f'images/{product}/security-policy.json']:
    self.assertIn(contract,workflow)
   discovery=(ROOT/'.github/workflows'/f'{product}-discover.yml').read_text()
   self.assertIn('--event pull_request',discovery);self.assertNotIn('--admin',discovery)
