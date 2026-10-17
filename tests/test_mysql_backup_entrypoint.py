import os,pathlib,signal,subprocess,tempfile,time,unittest
ENTRYPOINT=pathlib.Path(__file__).resolve().parents[1]/"images/mysql/backup/entrypoint.sh"
class MySQLBackupEntrypointTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=pathlib.Path(self.temp.name)
  self.env={k:v for k,v in os.environ.items() if not k.startswith("MYSQL")}
  self.env.update(PATH=str(self.root)+":"+os.environ["PATH"],CAPTURE=str(self.root/"capture"))
  launcher=self.root/"setsid";launcher.write_text("#!/usr/bin/env python3\nimport os,sys\nos.setsid()\nos.execvp(sys.argv[1],sys.argv[1:])\n");launcher.chmod(0o755)
 def tool(self,body,name="mysqldump"):
  p=self.root/name;p.write_text("#!/bin/sh\nset -eu\n"+body);p.chmod(0o755)
 def run_tool(self,*args):return subprocess.run([str(ENTRYPOINT),*args],env=self.env,capture_output=True,text=True,timeout=15)
 def test_private_option_file_and_atomic_dump(self):
  password=self.root/"password";password.write_text('public-test:"password\\suffix\n');self.env['MYSQL_PASSWORD_FILE']=str(password)
  self.tool('test "${MYSQL_PASSWORD+set}" != set\ntest "${MYSQL_PWD+set}" != set\np=${1#--defaults-file=}\nprintf "%s\\n" "$p" > "$CAPTURE"\ncat "$p" >> "$CAPTURE"\nprintf "%s\\n" "$@" >> "$CAPTURE"\nprintf complete\n')
  target=self.root/"dump.sql";result=self.run_tool("dump",str(target),"app")
  self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(target.read_text(),"complete")
  captured=(self.root/"capture").read_text();path=captured.splitlines()[0];self.assertFalse(pathlib.Path(path).exists())
  self.assertIn(r'password="public-test:\"password\\suffix"',captured)
  self.assertIn('ssl-mode="VERIFY_IDENTITY"',captured);self.assertIn('--single-transaction',captured);self.assertIn('--set-gtid-purged=OFF',captured)
  self.assertEqual(list(self.root.glob('dump.sql.partial.*')),[])
 def test_failed_dump_never_publishes_partial(self):
  self.tool('printf partial;exit 7\n');target=self.root/"dump.sql"
  self.assertEqual(self.run_tool('dump',str(target),'app').returncode,7);self.assertFalse(target.exists());self.assertEqual(list(self.root.glob('dump.sql.partial.*')),[])
 def test_invalid_database_existing_output_and_secret_conflicts(self):
  self.env.update(MYSQL_PASSWORD='public-test-password',MYSQL_PASSWORD_FILE='/unused')
  result=self.run_tool('mysql','--version');self.assertEqual(result.returncode,2);self.assertNotIn('public-test-password',result.stderr)
  del self.env['MYSQL_PASSWORD_FILE'];self.tool('exit 0\n')
  for db in ['mysql','sys','information_schema','performance_schema','--all-databases','app;DROP']:
   self.assertEqual(self.run_tool('dump',str(self.root/'out'),db).returncode,2)
  target=self.root/'out';target.write_text('keep');self.assertEqual(self.run_tool('dump',str(target),'app').returncode,2);self.assertEqual(target.read_text(),'keep')
  self.assertEqual(self.run_tool('mysql','--password=public-test').returncode,2)
 def test_restore_streams_file_to_native_mysql(self):
  self.tool('cat > "$CAPTURE"\n',name='mysql');source=self.root/'in.sql';source.write_text('SELECT 1;')
  self.assertEqual(self.run_tool('restore',str(source),'app').returncode,0);self.assertEqual((self.root/'capture').read_text(),'SELECT 1;')
 def test_cancel_waits_and_removes_partial(self):
  self.tool('trap \'printf stopped > "$CAPTURE";exit 143\' TERM\nprintf ready > "$CAPTURE"\nprintf partial\nwhile :;do :;done\n')
  target=self.root/'out';p=subprocess.Popen([str(ENTRYPOINT),'dump',str(target),'app'],env=self.env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  def cleanup():
   if p.poll() is None:p.kill()
   p.wait(timeout=5)
  self.addCleanup(cleanup)
  for _ in range(1000):
   if (self.root/'capture').exists():break
   time.sleep(.01)
  self.assertTrue((self.root/'capture').exists());p.send_signal(signal.SIGTERM);self.assertEqual(p.wait(timeout=15),143)
  self.assertEqual((self.root/'capture').read_text(),'stopped');self.assertFalse(target.exists());self.assertEqual(list(self.root.glob('out.partial.*')),[])
if __name__=='__main__':unittest.main()
