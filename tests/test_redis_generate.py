import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("redis_generate", ROOT / "tools/redis_generate.py")
generate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generate)
class RedisGenerateTests(unittest.TestCase):
    def test_committed_output_matches_lock(self):
        for path, content in generate.rendered_files(): self.assertEqual(path.read_text(), content)
    def test_client_only_recipe_keeps_sources_and_no_server_install(self):
        recipe = next(generate.rendered_files())[1]
        self.assertIn("sha256sum -c", recipe)
        self.assertIn("BUILD_TLS=yes", recipe)
        self.assertIn("restrict-checker.py", recipe)
        self.assertIn("/usr/share/redis-source/", recipe)
        self.assertIn("USER 10001:10001", recipe)
        self.assertIn('ENTRYPOINT ["/sbin/tini", "-g", "--", "docker-entrypoint.sh"]', recipe)
        self.assertNotIn("COPY --from=build /out/redis-server", recipe)
    def test_unreviewed_inputs_fail_closed(self):
        original = generate.IMAGE
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            lock = json.loads((original / "versions.lock.json").read_text())
            metadata = json.loads((original / "image.json").read_text())
            (dest / "image.json").write_text(json.dumps(metadata))
            for key, value in [("redis_version", "8.4.0"), ("source_sha256", "missing"), ("source_url", "https://example.com/source"), ("backup_base_image", "alpine:latest"), ("platforms", ["linux/amd64"]), ("official_source_commit", "main")]:
                candidate = copy.deepcopy(lock)
                candidate["releases"][0][key] = value
                (dest / "versions.lock.json").write_text(json.dumps(candidate))
                with self.subTest(key=key), patch.object(generate, "IMAGE", dest), self.assertRaises(ValueError): list(generate.rendered_files())
    def test_checker_patch_is_exact_and_fails_on_upstream_drift(self):
        import subprocess, sys
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "server.c"
            source.write_text('if (strstr(exec_name,"redis-check-rdb") != NULL)\n redis_check_rdb_main(argc,argv,NULL);')
            command = [sys.executable, str(ROOT / "images/redis/backup/restrict-checker.py"), str(source)]
            subprocess.run(command, check=True)
            self.assertIn("if (1)", source.read_text())
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
