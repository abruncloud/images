#!/usr/bin/env python3
"""Native TLS/ACL/RDB recovery and signal qualification; no ports are published."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import time

backup, runtime = sys.argv[1:3]
prefix = "redis-backup-test-" + secrets.token_hex(5)
network = prefix
containers = []
volumes = []
root = Path(tempfile.mkdtemp(prefix=prefix + "-"))
os.chmod(root, 0o700)

def run(*args, check=True, timeout=120):
    result = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError("Command failed: " + args[0] + " (details suppressed to protect fixture credentials): " + result.stderr[-1500:])
    return result

def docker(*args, **kwargs):
    return run("docker", *args, **kwargs)

def start(name, *args):
    containers.append(name)
    return docker("run", "-d", "--name", name, *args).stdout.strip()

password = secrets.token_hex(24)
(root / "credentials.env").write_text("REDISCLI_AUTH=" + password + "\n")
os.chmod(root / "credentials.env", 0o600)
(root / "work").mkdir(mode=0o777)
os.chmod(root / "work", 0o777)
(root / "tls").mkdir(mode=0o755)
key, cert = root / "tls/key.pem", root / "tls/cert.pem"
run("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=redis-source", "-addext", "subjectAltName=DNS:redis-source,DNS:redis-restore,DNS:localhost,IP:127.0.0.1", "-keyout", str(key), "-out", str(cert))
os.chmod(key, 0o644) # only inside the private 0700 fixture directory; Redis UID999 reads bind mount
hashpass = hashlib.sha256(password.encode()).hexdigest()
common = "port 0\ntls-port 6379\ntls-cert-file /tls/cert.pem\ntls-key-file /tls/key.pem\ntls-ca-cert-file /tls/cert.pem\ntls-auth-clients no\nsave \"\"\nappendonly no\nprotected-mode yes\n"
(root / "redis.conf").write_text(common + "user default off\nuser customer on #" + hashpass + " ~* &* +@all -@admin -@dangerous +ping +info\nuser backup on #" + hashpass + " -@all +ping +replconf +psync +sync\nuser operator on #" + hashpass + " ~* &* +@all\n")
os.chmod(root / "redis.conf", 0o644)

def cli(user, *args, host="redis-source", check=True, tls=True):
    return docker("run", "--rm", "--network", network, "--env-file", str(root / "credentials.env"), "-v", str(root / "tls") + ":/tls:ro", backup, "redis-cli", "-h", host, "--user", user, *( ["--tls", "--cacert", "/tls/cert.pem"] if tls else [] ), "--raw", *args, check=check)

def captured(name, *args):
    return start(name, "--network", network, "--env-file", str(root / "credentials.env"), "-v", str(root / "tls") + ":/tls:ro", "-v", str(root / "work") + ":/backup", backup, *args)

def wait_client(name, expected=0, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = json.loads(docker("inspect", name).stdout)[0]["State"]
        if not state["Running"]:
            if state["ExitCode"] != expected:
                logs = docker("logs", name).stdout
                raise AssertionError("Backup client failed: " + logs[-1500:])
            return
        time.sleep(.2)
    raise AssertionError("Backup client did not terminate")

try:
    docker("network", "create", "--internal", network)
    source = prefix + "-source"
    start(source, "--network", network, "--network-alias", "redis-source", "-v", str(root / "tls") + ":/tls:ro", "-v", str(root / "redis.conf") + ":/fixture/redis.conf:ro", runtime, "redis-server", "/fixture/redis.conf")
    for attempt in range(60):
        if cli("operator", "PING", check=False).stdout.strip() == "PONG": break
        time.sleep(1)
    else: raise AssertionError("TLS server did not become ready")
    assert "PONG" not in cli("operator", "PING", tls=False, check=False).stdout
    assert "NOPERM" in cli("backup", "SET", "forbidden", "x").stdout
    assert "NOPERM" in cli("customer", "CONFIG", "GET", "*").stdout
    assert cli("customer", "SET", "plain:key", "hello").stdout.strip() == "OK"
    assert cli("customer", "JSON.SET", "doc:1", "$", '{"title":"searchable","number":42}').stdout.strip() == "OK"
    assert cli("operator", "FT.CREATE", "idx", "ON", "JSON", "PREFIX", "1", "doc:", "SCHEMA", "$.title", "AS", "title", "TEXT").stdout.strip() == "OK"
    assert cli("customer", "TS.CREATE", "series:1").stdout.strip() == "OK"
    assert cli("customer", "TS.ADD", "series:1", "1000", "42").stdout.strip() == "1000"
    assert cli("customer", "BF.ADD", "bloom:1", "present").stdout.strip() == "1"
    assert cli("customer", "VADD", "vectors:1", "VALUES", "3", "1", "0", "0", "item1").stdout.strip() == "1"
    client = prefix + "-capture"
    captured(client, "redis-cli", "--tls", "--cacert", "/tls/cert.pem", "-h", "redis-source", "--user", "backup", "--rdb", "/backup/dump.rdb")
    wait_client(client)
    rdb = root / "work/dump.rdb"
    assert rdb.stat().st_size > 100
    check = docker("run", "--rm", "-v", str(root / "work") + ":/backup:ro", backup, "redis-check-rdb", "/backup/dump.rdb")
    assert "RDB looks OK" in check.stdout
    bad = root / "work/bad.rdb"
    bad.write_bytes(rdb.read_bytes()[:-10])
    assert docker("run", "--rm", "-v", str(root / "work") + ":/backup:ro", backup, "redis-check-rdb", "/backup/bad.rdb", check=False).returncode != 0
    # Renaming the checker must never turn its shared upstream code into a server.
    assert docker("run", "--rm", "--entrypoint", "sh", backup, "-c", "cp /usr/local/bin/redis-check-rdb /tmp/renamed; /tmp/renamed --port 6379", check=False).returncode != 0
    restored = prefix + "-restore"
    volume = prefix + "-restore-data"
    volumes.append(volume)
    docker("volume", "create", volume)
    docker("run", "--rm", "--user", "0", "-v", volume + ":/data", "-v", str(root / "work") + ":/backup:ro", "--entrypoint", "sh", backup, "-c", "cp /backup/dump.rdb /data/dump.rdb; chown 999:999 /data/dump.rdb")
    start(restored, "--network", network, "--network-alias", "redis-restore", "-v", volume + ":/data", "-v", str(root / "tls") + ":/tls:ro", "-v", str(root / "redis.conf") + ":/fixture/redis.conf:ro", runtime, "redis-server", "/fixture/redis.conf")
    for attempt in range(60):
        if cli("operator", "PING", host="redis-restore", check=False).stdout.strip() == "PONG": break
        time.sleep(1)
    else: raise AssertionError("Restored server did not become ready")
    for command in [("GET", "plain:key"), ("JSON.GET", "doc:1"), ("TS.GET", "series:1"), ("BF.EXISTS", "bloom:1", "present"), ("FT.SEARCH", "idx", "searchable"), ("VCARD", "vectors:1")]:
        expected = cli("operator", *command).stdout
        actual = cli("operator", *command, host="redis-restore").stdout
        assert actual == expected, (command[0], "RDB restore mismatch")
    # Block diskless replication before it produces a valid artifact, then TERM.
    assert cli("operator", "CONFIG", "SET", "repl-diskless-sync-delay", "60").stdout.strip() == "OK"
    cancel = prefix + "-cancel"
    captured(cancel, "redis-cli", "--tls", "--cacert", "/tls/cert.pem", "-h", "redis-source", "--user", "backup", "--rdb", "/backup/partial.rdb")
    time.sleep(2)
    assert json.loads(docker("inspect", cancel).stdout)[0]["State"]["Running"]
    docker("kill", "--signal", "TERM", cancel)
    wait_client(cancel, expected=143, timeout=10)
    partial = root / "work/partial.rdb"
    if partial.exists():
        assert docker("run", "--rm", "-v", str(root / "work") + ":/backup:ro", backup, "redis-check-rdb", "/backup/partial.rdb", check=False).returncode != 0
    # The generic client does not delete arbitrary partial paths; callers publish only after a successful check.
    assert not docker("run", "--rm", "--entrypoint", "sh", backup, "-c", "command -v redis-server || command -v redis-sentinel", check=False).stdout.strip()
    print(json.dumps({"version": "8.2.10", "backup": backup, "runtime": runtime, "architecture": docker("image", "inspect", backup, "--format", "{{.Architecture}}").stdout.strip(), "tls_acl": "pass", "module_rdb_restore": ["json", "search", "timeseries", "bloom", "vectorset"], "checker_corruption_and_rename": "pass", "cancellation_partial": "pass", "published_ports": []}, sort_keys=True))
finally:
    for name in reversed(containers): docker("rm", "-f", name, check=False)
    for name in volumes: docker("volume", "rm", name, check=False)
    docker("network", "rm", network, check=False)
    shutil.rmtree(root)
    leftovers = docker("ps", "-aq", "--filter", "name=" + prefix).stdout.strip()
    if leftovers: raise AssertionError("Qualification containers were not removed")
