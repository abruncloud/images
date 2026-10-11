import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import discover
import release
import publish

class AutomationTests(unittest.TestCase):
    def test_aliases_no_latest_and_backup_suffix(self):
        metadata, lock = release.load()
        for item in lock["releases"]:
            runtime = release.tags(item["major"], item["variant"], "runtime")
            if item["variant"] == metadata["backup_variant"]:
                backup = release.tags(item["major"], item["variant"], "backup")
                self.assertIn("abruncloud/postgres:" + item["major"] + "-backup", backup)
                self.assertIn("abruncloud/postgres:" + item["postgres_version"] + "-backup", backup)
                self.assertTrue(all(tag.endswith("-backup") for tag in backup))
            else:
                with self.assertRaisesRegex(ValueError, "Unsupported image target"):
                    release.tags(item["major"], item["variant"], "backup")
            self.assertIn("abruncloud/postgres:" + item["postgres_version"] + "-" + item["variant"], runtime)
            self.assertFalse(any("latest" in tag for tag in runtime))
            if item["variant"] == metadata["default_variant"]:
                self.assertIn("abruncloud/postgres:" + item["major"], runtime)
            if item["variant"] == metadata["default_alpine_variant"]:
                self.assertIn("abruncloud/postgres:" + item["major"] + "-alpine", runtime)

    def test_native_matrix_covers_every_variant(self):
        metadata, lock = release.load()
        entries = release.matrix()["include"]
        self.assertEqual({(entry["major"], entry["variant"], entry["arch"]) for entry in entries}, {
            (item["major"], item["variant"], arch) for item in lock["releases"] for arch in ["amd64", "arm64"]})
        self.assertEqual(sum(entry["backup"] for entry in entries), 2)
        self.assertTrue(all(entry["backup"] == (entry["variant"] == metadata["backup_variant"]) for entry in entries))
        self.assertTrue(all(entry["runner"].endswith("-arm") == (entry["arch"] == "arm64") for entry in entries))

    def test_registry_requires_both_architectures(self):
        raw = json.dumps({"manifests": [{"platform": {"os": "linux", "architecture": "amd64"}}]}).encode()
        import hashlib
        with patch.object(discover, "fetch", side_effect=[(b'{"token":"token"}', {}),
                (raw, {"Docker-Content-Digest": "sha256:" + hashlib.sha256(raw).hexdigest()})]):
            with self.assertRaisesRegex(ValueError, "native platforms"):
                discover.resolve("18.6-trixie")

    def test_registry_digest_is_verified(self):
        with patch.object(discover, "fetch", side_effect=[(b'{"token":"token"}', {}),
                (b'{}', {"Docker-Content-Digest": "sha256:" + "0" * 64})]):
            with self.assertRaisesRegex(ValueError, "digest verification"):
                discover.resolve("18.6-trixie")

    def test_stale_publication_never_calls_docker(self):
        with patch.dict("os.environ", {"EXPECTED_SHA": "a" * 40}), patch.object(publish, "current_main", return_value="b" * 40), patch.object(publish, "command") as command:
            with self.assertRaisesRegex(SystemExit, "stale publication"):
                publish.main()
            command.assert_not_called()


class HardeningDiscoveryTests(unittest.TestCase):
    def compiler(self, version="1.27.2", digest="a", variant="trixie"):
        return {"version": version, "base_image": "docker.io/library/golang:" + version + "-" + variant + "@sha256:" + digest * 64}

    def lock(self):
        return {"schema_version": 1, "pgvector": {"version": "0.8.7", "sha256": "vector"},
                "gosu": {"version": "1.19", "sha256": "gosu"}, "go": self.compiler(), "releases": []}

    def test_go_patch_and_base_rebuild_remain_routine(self):
        old = self.lock()
        new = {**old, "go": self.compiler("1.27.3", "b"), "releases": [{"postgres_version": "18.7"}]}
        self.assertEqual(discover.review_inputs(old), discover.review_inputs(new))

    def test_go_new_line_or_distribution_requires_review(self):
        old = self.lock()
        for compiler in [self.compiler("1.28.0"), self.compiler(variant="bookworm")]:
            with self.subTest(compiler=compiler):
                self.assertNotEqual(discover.review_inputs(old), discover.review_inputs({**old, "go": compiler}))

    def test_all_gosu_and_vector_inputs_require_review(self):
        old = self.lock()
        for key in ["gosu", "pgvector"]:
            new = {**old, key: {**old[key], "sha256": "changed"}}
            self.assertNotEqual(discover.review_inputs(old), discover.review_inputs(new))
        self.assertNotEqual(discover.review_inputs(old), discover.review_inputs({**old, "future_dependency": {"version": "1"}}))

    def test_hardening_uses_stable_official_go_tags_and_checksums_gosu(self):
        import hashlib
        current = self.lock()
        urls = {
            "https://api.github.com/repos/tianon/gosu/releases/latest": json.dumps({"tag_name": "1.19", "draft": False, "prerelease": False}).encode(),
            "https://github.com/tianon/gosu/archive/refs/tags/1.19.tar.gz": b"verified source fixture",
            "https://raw.githubusercontent.com/docker-library/official-images/master/library/golang": b"Tags: 1.27.3-trixie, 1.28rc1-trixie, 1.26.10-trixie\n",
        }
        with patch.object(discover, "fetch", side_effect=lambda url, headers=None: (urls[url], {})), patch.object(discover, "resolve", return_value=(self.compiler("1.27.3")["base_image"], ["linux/amd64", "linux/arm64"])) as resolve:
            gosu, go = discover.discover_hardening(current)
        self.assertEqual(gosu["sha256"], hashlib.sha256(b"verified source fixture").hexdigest())
        self.assertEqual(gosu["version"], "1.19")
        self.assertEqual(go["version"], "1.27.3")
        resolve.assert_called_once_with("1.27.3-trixie", repository="golang")

    def test_gosu_prereleases_fail_closed(self):
        with patch.object(discover, "fetch", return_value=(b'{"tag_name":"1.20","prerelease":true}', {})):
            with self.assertRaisesRegex(ValueError, "stable numeric gosu"):
                discover.discover_hardening(self.lock())

    def test_unknown_registry_repository_is_rejected(self):
        with patch.object(discover, "fetch") as fetch:
            with self.assertRaisesRegex(ValueError, "official image repository"):
                discover.resolve("version", repository="unknown")
            fetch.assert_not_called()

    def test_discovery_preserves_other_lock_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "images/postgres"
            image.mkdir(parents=True)
            current = {**self.lock(), "future_dependency": {"version": "1"}}
            (image / "versions.lock.json").write_text(json.dumps(current))
            (image / "image.json").write_text(json.dumps({"supported_majors": ["18"], "variants": ["trixie"], "backup_variant": "alpine3.24"}))
            def fetch(url, headers=None):
                if url.endswith("/library/postgres"):
                    return b"Tags: 18.6-trixie, 18-trixie\n", {}
                if "/pgvector/tags" in url:
                    return b'[{"name":"v0.8.7"}]', {}
                if url.endswith("v0.8.7.tar.gz"):
                    return b"vector archive", {}
                raise AssertionError("Unexpected source " + url)
            with patch.object(discover, "ROOT", root), patch.object(discover, "fetch", side_effect=fetch), patch.object(discover, "resolve", return_value=("pinned", ["linux/amd64", "linux/arm64"])), patch.object(discover, "discover_hardening", return_value=(current["gosu"], current["go"])):
                updated = discover.discover()
            self.assertEqual(updated["future_dependency"], current["future_dependency"])
            self.assertEqual(updated["gosu"], current["gosu"])
            self.assertEqual(updated["go"], current["go"])
            self.assertEqual(updated["releases"][0]["postgres_version"], "18.6")

class DiscoveryAuthenticationTests(unittest.TestCase):
    def request(self, url, token="test-token", headers=None):
        import os
        from unittest.mock import MagicMock
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b"response"
        response.headers = {}
        environment = {"GH_TOKEN": token} if token is not None else {}
        with patch.dict(os.environ, environment, clear=True), patch.object(discover.urllib.request, "urlopen", return_value=response) as open_request:
            discover.fetch(url, headers)
        return open_request.call_args.args[0]

    def test_token_is_only_sent_to_exact_https_github_api(self):
        for url in ["https://api.github.com/repos/pgvector/pgvector/tags", "https://api.github.com:443/repos/tianon/gosu/releases/latest"]:
            request = self.request(url)
            self.assertEqual(request.get_header("Authorization"), "Bearer test-token")
            self.assertNotIn("Authorization", request.headers)

    def test_other_origins_never_receive_github_token(self):
        for url in ["http://api.github.com/repos", "https://api.github.com:8443/repos", "https://api.github.com.evil.invalid/repos",
                    "https://user@api.github.com/repos", "https://api.github.com@evil.invalid/repos", "https://github.com/archive", "https://raw.githubusercontent.com/source",
                    "https://auth.docker.io/token", "https://registry-1.docker.io/v2"]:
            with self.subTest(url=url):
                self.assertIsNone(self.request(url).get_header("Authorization"))

    def test_absent_token_keeps_local_discovery_anonymous(self):
        self.assertIsNone(self.request("https://api.github.com/repos", token=None).get_header("Authorization"))
        self.assertIsNone(self.request("https://api.github.com/repos", token="").get_header("Authorization"))

    def test_redirects_never_forward_github_token(self):
        request = self.request("https://api.github.com/repos")
        handler = discover.urllib.request.HTTPRedirectHandler()
        for target in ["https://api.github.com/moved", "https://codeload.github.com/archive", "https://evil.invalid/archive", "http://api.github.com/moved"]:
            with self.subTest(target=target):
                redirected = handler.redirect_request(request, None, 302, "Found", {}, target)
                self.assertIsNone(redirected.get_header("Authorization"))

    def test_registry_authorization_remains_its_own_token(self):
        request = self.request("https://registry-1.docker.io/v2/library/postgres/manifests/tag", headers={"Authorization": "Bearer registry-token"})
        self.assertEqual(request.get_header("Authorization"), "Bearer registry-token")


class BackupBaseDiscoveryTests(unittest.TestCase):
    def test_backup_base_refresh_is_routine(self):
        current = json.loads((discover.ROOT / "images/postgres/versions.lock.json").read_text())
        import copy
        updated = copy.deepcopy(current)
        for item in updated["releases"]:
            if "backup_base_image" not in item:
                continue
            item["backup_base_image"] = item["backup_base_image"].split("@", 1)[0] + "@sha256:" + "f" * 64
        self.assertEqual(discover.review_inputs(current), discover.review_inputs(updated))

    def test_clean_base_resolver_requires_verified_native_platforms(self):
        import hashlib
        raw = json.dumps({"manifests": [{"platform": {"os": "linux", "architecture": arch}} for arch in ["amd64", "arm64"]]}).encode()
        digest = "sha256:" + hashlib.sha256(raw).hexdigest()
        for repository, tag in [("debian", "trixie-slim"), ("alpine", "3.24")]:
            with self.subTest(repository=repository), patch.object(discover, "fetch", side_effect=[(b'{"token":"registry"}', {}), (raw, {"Docker-Content-Digest": digest})]) as fetch:
                image, platforms = discover.resolve(tag, repository=repository)
                self.assertEqual(image, "docker.io/library/" + repository + ":" + tag + "@" + digest)
                self.assertEqual(platforms, ["linux/amd64", "linux/arm64"])
                self.assertIn("library/" + repository + ":pull", fetch.call_args_list[0].args[0])

    def test_discovery_refreshes_correct_clean_base_without_changing_supported_major(self):
        current = json.loads((discover.ROOT / "images/postgres/versions.lock.json").read_text())
        seen = []
        def resolve(tag, repository="postgres"):
            seen.append((repository, tag))
            return "docker.io/library/" + repository + ":" + tag + "@sha256:" + "f" * 64, ["linux/amd64", "linux/arm64"]
        def fetch(url, headers=None):
            if url.endswith("/library/postgres"):
                return b"Tags: 18.6-trixie, 18.6-alpine3.24\n", {}
            if "/pgvector/tags" in url:
                return b'[{"name":"v0.8.7"}]', {}
            if url.endswith("v0.8.7.tar.gz"):
                return b"source", {}
            raise AssertionError("Unexpected source " + url)
        with patch.object(discover, "resolve", side_effect=resolve), patch.object(discover, "fetch", side_effect=fetch), patch.object(discover, "discover_hardening", return_value=(current["gosu"], current["go"])):
            updated = discover.discover()
        self.assertNotIn(("debian", "trixie-slim"), seen)
        self.assertIn(("alpine", "3.24"), seen)
        self.assertEqual({item["major"] for item in updated["releases"]}, {"18"})
        self.assertTrue(all(item["backup_base_image"].endswith("@sha256:" + "f" * 64) for item in updated["releases"] if item["variant"] == "alpine3.24"))
        self.assertTrue(all("backup_base_image" not in item for item in updated["releases"] if item["variant"] == "trixie"))


if __name__ == "__main__":
    unittest.main()
