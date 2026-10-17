# Redis client-only backup tools

`abruncloud/redis` supplies Redis 8.2 client tools on Alpine 3.22 for Linux amd64
and arm64. It does not supply a database server. Use the pinned Docker Official
`redis:8.2.10-bookworm` image for the server; its entrypoint loads the bundled
JSON, Search, TimeSeries and Bloom modules on supported architectures.

## Tags

The published aliases are `8.2.10-backup`, `8.2-backup`,
`8.2.10-alpine3.22-backup` and `8.2-alpine3.22-backup`. All resolve to the same
qualified multi-architecture index. No runtime or `build-*` tags are published to
Docker Hub. Production deployments should pin the index digest from the release
record. Publishing a newer alias never updates existing instances.

## Contents and behavior

The image includes TLS-enabled `redis-cli`, `redis-check-rdb`, curl, jq, Python 3,
tar, gzip, coreutils (including sha256sum and timeout), setsid and `/bin/setpriv` for callers that explicitly run a protected bootstrap
before dropping privileges and capabilities. The default
user is UID/GID 10001; `/backup` is writable by that user. Bind mounts need matching
permissions. The entrypoint sets a private umask, forwards arguments verbatim,
and executes commands under tini with process-group signal forwarding. This avoids
Linux PID 1 ignoring the client’s default TERM disposition and reaps child
processes. Arguments starting
with `-` are passed to `redis-cli`. No ports or server credentials are baked in.

Redis upstream implements `redis-check-rdb` inside the server executable and
selects it by executable name. Our one-line source modification unconditionally
selects its checker branch, before server option parsing. Renaming it or passing
server flags cannot start a server. No server, Sentinel, modules, compiler or build
packages are installed in the final image. Redis CLI source is unmodified.

## Capture and restore

Use a dedicated ACL account, with only `+ping +replconf +sync` (the qualification
also permits `+psync` for future protocol compatibility), and a secure private
connection. RDB capture uses replication commands and reads the **entire** Redis
instance; key-pattern ACLs cannot isolate a partial backup. Never grant this
account to database clients. A successful RDB captures a consistent point in time;
subsequent writes are outside that snapshot. It is not a continuous backup/PITR.

```sh
# Keep REDISCLI_AUTH in a protected env file, not a command-line password.
docker run --rm --network database-network \
  --env-file ./credentials.env -v ./ca.pem:/ca.pem:ro -v ./backups:/backup \
  abruncloud/redis:8.2.10-backup \
  redis-cli --tls --cacert /ca.pem -h redis-host --user backup \
  --rdb /backup/dump.rdb.partial
# Validate before atomically renaming/uploading an artifact.
docker run --rm -v ./backups:/backup:ro abruncloud/redis:8.2.10-backup \
  timeout --signal=KILL 120s redis-check-rdb /backup/dump.rdb.partial
```

Redis 8.2.10’s upstream checker can stall on a truncated RDB containing module
values; this was independently reproduced with the unchanged official server
image. Bound validation with `timeout` as above. A timeout is a failed validation,
never a valid backup. The raw upstream parser is retained; no parser fork or
corruption exception is applied. Qualification requires valid module data to
check and restore successfully, and truncated input to reject directly or by
the explicit deadline.

A supervisor must remove partial output after failure/cancellation and publish
only after client exit zero plus a successful RDB check. The generic client does
not delete caller-owned paths automatically. TERM closes its replication
connection. Server snapshot work already started may finish independently; no
successful artifact should be inferred from a terminated client.

For manual restore, stop a fresh compatible Redis instance, put the checked RDB
at its configured `dir`/`dbfilename` with correct ownership, then start it. RDBs
containing module values require matching compatible server modules. Qualification
restores JSON/Search index/TimeSeries/Bloom and built-in vector-set values into
the exact official server release on each architecture. Cross-version restores
and server upgrades require separate compatibility checks.

## Rebuild and qualification

```sh
python3 tools/redis_generate.py --check
docker build -f images/redis/generated/8.2/alpine3.22/Dockerfile.backup \
  -t redis-backup:test .
bash tests/run-redis-backup.sh redis-backup:test \
  docker.io/library/redis:8.2.10-bookworm@sha256:47670742d7924adbcdb404d1288b6327815b23141969c0939b8e5d61f78c2634
```

Native tests verify TLS and ACLs, snapshot/recovery of integrated module data,
corruption rejection, checker rename/flag safety, cancellation with partial
output, and removal of all owned fixtures. They publish no ports. Complete
vulnerability reports, SBOM, provenance, signed digests and input locks accompany
each release. The reviewed actionable gate blocks fixable HIGH and all CRITICAL
findings; there are no Redis-specific exceptions.

## Source and licensing

Redis 8 offers AGPLv3, SSPLv1 and RSALv2 choices. This modified client build is
conveyed under AGPLv3. Upstream notices and complete license text are retained at
`/usr/share/licenses/redis/LICENSE.txt`. The exact checksum-verified source
archive, checker modification and build recipe are included under
`/usr/share/redis-source/`, alongside the corresponding public repository commit
recorded in release provenance. The archive includes upstream bundled dependency
sources and notices. Alpine packages retain their own licenses and source
availability. The tools are generic and contain no Abrun platform-specific jobs.

Discovery follows only the explicitly reviewed `8.2` line and Alpine 3.22, using
the official-image source Dockerfile checksum. Patch/source/base changes open
qualified update PRs; major/minor lines and distribution changes require review.
