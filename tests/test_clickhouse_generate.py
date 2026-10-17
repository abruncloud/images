import importlib.util,json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import clickhouse_generate,clickhouse_discover,release
class ClickHouseRecipeTests(unittest.TestCase):
 def test_generated_client_only_contract(self):
  files=dict(clickhouse_generate.rendered_files());self.assertEqual(len(files),1)
  for path,text in files.items():
   self.assertEqual(path.read_text(),text)
   self.assertIn('CGO_ENABLED=0 go build',text)
   self.assertIn('USER 10001:10001',text)
   self.assertIn('apk upgrade --no-cache',text)
   self.assertNotIn('common-static',text)
   self.assertIn('go mod verify',text)
   self.assertIn('COPY --from=build /licenses/',text)
 def test_backup_tags_do_not_publish_server_or_build_aliases(self):
  self.assertEqual(set(release.tags('26.8','alpine3.22','backup','clickhouse')),{
   'abruncloud/clickhouse:26.8.28.14-backup','abruncloud/clickhouse:26.8-backup',
   'abruncloud/clickhouse:26.8.28.14-alpine3.22-backup','abruncloud/clickhouse:26.8-alpine3.22-backup'})
  with self.assertRaises(ValueError):release.tags('26.8','alpine3.22','runtime','clickhouse')
 def test_native_matrix(self):
  entries=release.matrix('backup','clickhouse')['include']
  self.assertEqual({x['arch'] for x in entries},{'amd64','arm64'})
  self.assertTrue(all(x['backup'] for x in entries))
 def test_routine_updates_preserve_release_and_driver_boundaries(self):
  lock=json.loads((ROOT/'images/clickhouse/versions.lock.json').read_text());before=clickhouse_discover.review_inputs(lock)
  patch=json.loads(json.dumps(lock));item=patch['releases'][0];item['clickhouse_version']='26.8.29.10';item['base_image']='docker.io/library/clickhouse:26.8.29.10-jammy@sha256:'+'a'*64
  self.assertEqual(before,clickhouse_discover.review_inputs(patch))
  patch['client']['driver_version']='2.50.0';self.assertNotEqual(before,clickhouse_discover.review_inputs(patch))
 def test_release_gates_native_security_architecture(self):
  workflow=(ROOT/'.github/workflows/clickhouse-release.yml').read_text()
  self.assertIn('tests/run-clickhouse-backup.sh',workflow)
  self.assertIn('TRIVY_PLATFORM: linux/${{ matrix.arch }}',workflow)
  self.assertIn('Scanner architecture mismatch',workflow)
  self.assertIn('tools/security_gate.py --policy images/clickhouse/security-policy.json',workflow)
  self.assertIn('needs: [metadata, qualify]',workflow)
  self.assertIn('sbom: true',workflow)
 def test_pull_request_checks_are_required_and_real(self):
  workflow=(ROOT/'.github/workflows/check.yml').read_text();self.assertIn('clickhouse-native-test, mongodb-native-test, mongodb-exporter-native-test]',workflow)
  self.assertIn('test "$CLICKHOUSE_TESTS" = success',workflow)
  workflow=(ROOT/'.github/workflows/clickhouse-discover.yml').read_text();self.assertIn('--event pull_request',workflow)
  self.assertNotIn('--admin',workflow)
