"""Deterministic wrapper tests without database or Docker dependencies."""
import os
import pathlib
import signal
import subprocess
import tempfile
import time
import unittest

ENTRYPOINT = pathlib.Path(__file__).resolve().parents[1] / "images/postgres/backup/entrypoint.sh"


class BackupEntrypointTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)
        self.environment = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
        self.environment.update(PATH=str(self.root) + ":" + os.environ["PATH"], CAPTURE=str(self.root / "capture"))

    def tool(self, body):
        path = self.root / "pg_dump"
        path.write_text("#!/bin/sh\nset -eu\n" + body)
        path.chmod(0o755)

    def run_command(self, *arguments):
        return subprocess.run([str(ENTRYPOINT), *arguments], env=self.environment, capture_output=True, text=True, timeout=15)

    def test_file_credentials_escape_pgpass_and_are_removed_after_child(self):
        password = self.root / "password"
        password.write_text("public-test:password\\suffix\n")
        password.chmod(0o600)
        host = self.root / "host"
        host.write_text("database.example\n")
        self.environment.update(PGPASSWORD_FILE=str(password), PGHOST_FILE=str(host))
        self.tool('test "${PGPASSWORD+set}" != set\nprintf "%s\\n" "$PGHOST" "$PGPASSFILE" > "$CAPTURE"\ncat "$PGPASSFILE" >> "$CAPTURE"\nprintf "%s\\n" "$@" >> "$CAPTURE"\n')
        result = self.run_command("dump", str(self.root / "dump"))
        self.assertEqual(result.returncode, 0, result.stderr)
        captured = (self.root / "capture").read_text().splitlines()
        self.assertEqual(captured[0], "database.example")
        self.assertFalse(pathlib.Path(captured[1]).exists())
        self.assertEqual(captured[2], r"*:*:*:*:public-test\:password\\suffix")
        self.assertIn("--format=custom", captured)

    def test_file_and_environment_conflict_does_not_expose_password(self):
        self.environment.update(PGPASSWORD="public-test-password", PGPASSWORD_FILE="/unused")
        result = self.run_command("pg_dump", "--version")
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("public-test-password", result.stdout + result.stderr)

    def test_unsupported_command_is_not_executed(self):
        self.assertEqual(self.run_command("unsupported-command").returncode, 2)
        self.assertEqual(self.run_command("dump").returncode, 2)

    def test_native_failure_status_is_preserved(self):
        self.tool("exit 7\n")
        self.assertEqual(self.run_command("pg_dump").returncode, 7)

    def test_term_is_forwarded_and_waits_for_child_cleanup(self):
        self.tool('trap \'sleep 0.2; printf terminated > "$CAPTURE"; exit 143\' TERM\nprintf ready > "$CAPTURE"\nwhile :; do :; done\n')
        process = subprocess.Popen([str(ENTRYPOINT), "pg_dump"], env=self.environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        def cleanup_process():
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
        self.addCleanup(cleanup_process)
        for _ in range(1000):
            if (self.root / "capture").exists():
                break
            time.sleep(0.01)
        self.assertTrue((self.root / "capture").exists())
        process.send_signal(signal.SIGTERM)
        self.assertEqual(process.wait(timeout=15), 143)
        self.assertEqual((self.root / "capture").read_text(), "terminated")

    def test_term_reaches_native_descendants(self):
        # Portable setsid fixture exercises Linux image behaviour on macOS too.
        launcher = self.root / "setsid"
        launcher.write_text("#!/usr/bin/env python3\nimport os,sys\nos.setsid()\nos.execvp(sys.argv[1],sys.argv[1:])\n")
        launcher.chmod(0o755)
        child = self.root / "descendant.py"
        child.write_text("import os,signal,time\nfrom pathlib import Path\np=Path(os.environ['CAPTURE']+'.child')\nsignal.signal(signal.SIGTERM,lambda *args: (p.write_text('terminated'),exit(0)))\np.write_text('ready')\nwhile True: time.sleep(.01)\n")
        self.tool('python3 "'+str(child)+'" &\ntrap \'wait; exit 143\' TERM\nwait\n')
        process = subprocess.Popen([str(ENTRYPOINT), "pg_dump"], env=self.environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        def cleanup_process():
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
        self.addCleanup(cleanup_process)
        captured = self.root / "capture.child"
        for _ in range(1000):
            if captured.exists():
                break
            time.sleep(.01)
        self.assertTrue(captured.exists())
        process.send_signal(signal.SIGTERM)
        self.assertEqual(process.wait(timeout=15), 143)
        self.assertEqual(captured.read_text(), "terminated")


if __name__ == "__main__":
    unittest.main()
