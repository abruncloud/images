# MySQL backup clients

The published `abruncloud/mysql` images contain MySQL client tools only. The first supported release line is MySQL 8.4 on Oracle Linux 9, with native Linux amd64 and arm64 qualification. Server Dockerfile definitions are retained for future reference; publication builds and pushes only backup images. Run the original [Docker Official MySQL image](https://github.com/docker-library/mysql) for your database server.

The lock records the exact MySQL client RPM version, an immutable official server image used for native recovery tests and the immutable Oracle Linux base. Existing instances should pin image digests. Moving aliases discover new releases and do not upgrade a running instance.

## Tags

- `8.4.11-backup`, `8.4-backup`
- `8.4.11-oraclelinux9-backup`, `8.4-oraclelinux9-backup`

No runtime aliases or `build-*` tags are published to Docker Hub. Temporary build candidates stay in GHCR. Releases include signed native and multiarchitecture digests, SBOM, provenance, vulnerability reports and a retained release record.

## Backup and restore

The image contains `mysql`, `mysqldump`, `mysqladmin`, `mysqlbinlog`, `setsid`, `curl`, `jq`, Python 3, tar, gzip and core Unix tools. It contains no `mysqld`, server initialization scripts, embedded credentials, data volume or published port. A platform can override the entrypoint to run its own mounted scripts.

The generic entrypoint uses `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE`, `MYSQL_SSL_MODE`, and `MYSQL_SSL_CA`. Each supports a corresponding `_FILE` variable. Set only one of a value and its `_FILE` alternative. Passwords go into a temporary private option file and never into command arguments. Verified TLS (`VERIFY_IDENTITY`) is the default; mount a trusted CA and use a matching server name.

```sh
docker run --rm --network your-private-network \
  -e MYSQL_HOST=mysql -e MYSQL_USER=backup -e MYSQL_DATABASE=app \
  -e MYSQL_PASSWORD_FILE=/run/secrets/password \
  -e MYSQL_SSL_CA=/run/secrets/ca.crt \
  -v /secure/password:/run/secrets/password:ro \
  -v /secure/ca.crt:/run/secrets/ca.crt:ro \
  -v /backups:/output \
  abruncloud/mysql:8.4.11-backup dump /output/app.sql app
```

Use `restore /output/app.sql app` against a prepared target database with an appropriately authorized user. Users remain responsible for restoration. Logical captures include views, routines, triggers and events; they use `--single-transaction --quick --no-tablespaces --set-gtid-purged=OFF`. Consistency requires InnoDB tables and no concurrent DDL. There is no physical backup or point-in-time recovery support. Account privileges and definer portability must be qualified for the target workload.

Dump files publish atomically without overwriting an existing file. Failed or cancelled captures remove partial files. The entrypoint forwards termination to its client process group. Client termination does not guarantee immediate server-side cancellation of a statement blocked on a metadata lock. Coordinators that require that guarantee must separately terminate and verify their own backup sessions.

## Build and qualification

```sh
python3 tools/mysql_generate.py --check
docker build -f images/mysql/generated/8.4/oraclelinux9/Dockerfile.backup -t mysql-backup:test .
# Supply the immutable original server reference from versions.lock.json.
bash tests/run-mysql-backup.sh mysql-backup:test mysql:8.4.11-oraclelinux9
```

CI uses the exact locked original server digest on each native architecture. It checks client-only packaging, required script tools, `caching_sha2_password` authentication, verified TLS, dump/restore of data/views/routines/events/triggers, capture errors and cancellation. Only the qualified backup digest passes the actionable security gate and proceeds to Docker Hub promotion. All CRITICAL findings and fixable HIGH findings block publication; unfixed HIGH findings remain reported. MySQL has no security exceptions.
