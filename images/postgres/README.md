# AbrunCloud PostgreSQL

Official PostgreSQL images with pgvector included on Debian and Alpine. The runtime preserves the official image's entrypoint, initialization variables, signal handling and persistent-data layout. These images work independently of Abrun.

## Versions and tags

The first supported line is PostgreSQL 18, on Debian trixie and Alpine 3.24, for `linux/amd64` and `linux/arm64`. Exact inputs are recorded in [versions.lock.json](versions.lock.json). Release tags are published only after their tests pass; repository availability does not imply an image has already been published.

For a resolved PostgreSQL version `18.x`, runtime aliases are:

| Debian | Alpine |
| --- | --- |
| `18`, `18.x` | `18-alpine`, `18.x-alpine` |
| `18-trixie`, `18.x-trixie` | `18-alpine3.24`, `18.x-alpine3.24` |

The single backup artifact uses Alpine for both supported architectures. Its aliases are `18-backup`, `18.x-backup`, `18-alpine-backup`, `18.x-alpine-backup`, `18-alpine3.24-backup`, and `18.x-alpine3.24-backup`; every alias names the same qualified Alpine client image. Debian runtime aliases remain available; Debian backup builds and `-trixie-backup` aliases are no longer published. The backup image contains client tools only, with no PostgreSQL server or initialization entrypoint.

Tags can receive a qualified rebuild when base packages or pgvector change. Pin `abruncloud/postgres@sha256:...` when reproducibility matters. Published release records identify the exact input versions and image digests. Existing deployments do not update themselves.

## Quick start

```sh
docker run -d --name postgres \
  --mount type=volume,src=postgres-data,dst=/var/lib/postgresql \
  --mount type=bind,src="$PWD/postgres-password",dst=/run/secrets/postgres-password,readonly \
  -e POSTGRES_PASSWORD_FILE=/run/secrets/postgres-password \
  -e POSTGRES_DB=app \
  abruncloud/postgres:18
docker exec postgres psql -U postgres -d app -c 'CREATE EXTENSION vector;'
```

Create the password file beforehand and restrict access to it. The example intentionally does not publish a network port. For local host access, add `-p 127.0.0.1:5432:5432`; remote access needs appropriate authentication, TLS and network policy.

## Upstream compatibility

The [official PostgreSQL documentation](https://hub.docker.com/_/postgres) remains the reference for runtime configuration. Supported upstream settings include `POSTGRES_PASSWORD`, `POSTGRES_USER`, `POSTGRES_DB`, `POSTGRES_INITDB_ARGS`, `POSTGRES_INITDB_WALDIR`, `POSTGRES_HOST_AUTH_METHOD`, `PGDATA`, and upstream-supported `*_FILE` alternatives. A variable and its `_FILE` alternative cannot both be set.

Initialization variables and `/docker-entrypoint-initdb.d` SQL/shell scripts apply only to an empty data directory. They do not update users, passwords or extensions in an existing cluster. Failed initialization stops startup; inspect the logs and recover or recreate the partially initialized volume before retrying.

PostgreSQL 18 inherits `PGDATA=/var/lib/postgresql/18/docker`. Mount persistent storage at `/var/lib/postgresql`, rather than assuming the pre-18 `/var/lib/postgresql/data` layout. Debian and Alpine use different PostgreSQL user IDs; do not move a volume between distributions without handling ownership and database/locale compatibility.

The inherited entrypoint can initialize a writable volume as root and then drop to the PostgreSQL user. Running directly as that user requires pre-owned writable storage. Keep sufficient shutdown time: the inherited `SIGINT` stop signal requests PostgreSQL fast shutdown.

## Extensions and configuration

pgvector is compiled against the matching PostgreSQL installation, with CPU-specific compiler optimizations disabled so the image does not require the builder's CPU model. Its exact release and source checksum are locked. Compilers and build dependencies remain in the build stage.

The tested extension inventory is `vector`, `pg_trgm`, `pg_stat_statements`, `uuid-ossp`, `btree_gin`, `btree_gist`, and `pgcrypto`. Extensions are installed but not automatically created in customer databases. Enable the ones required with `CREATE EXTENSION`. `pg_stat_statements` additionally requires its documented `shared_preload_libraries` configuration. Other contributed extensions inherited from upstream are not a promise of tested support.

Native command arguments and mounted configuration work normally:

```sh
docker run --rm \
  --mount type=volume,src=postgres-data,dst=/var/lib/postgresql \
  --mount type=bind,src="$PWD/postgresql.conf",dst=/etc/postgresql/postgresql.conf,readonly \
  abruncloud/postgres:18 postgres -c config_file=/etc/postgresql/postgresql.conf
```

Size memory settings and connection limits for your actual container resources and workload. The images do not read an Abrun plan or rewrite configuration on each startup. Alpine uses musl rather than glibc; locale and collation behavior can differ. Treat switching distributions as a migration, not a tag replacement.

## Backup images

The Alpine backup image is an independently packaged client artifact. It includes `pg_dump`, `pg_restore`, `pg_basebackup`, `pg_verifybackup`, `pg_waldump`, and `psql`, the shared libraries those tools require, and the small `postgres-backup` wrapper. It contains no `postgres`, `initdb`, `pg_ctl`, or upstream server entrypoint, and declares no `PGDATA`, persistent volumes, or exposed database port. No extension binaries are needed in a backup client: logical restoration and physical recovery use extensions installed in the destination runtime.

The wrapper uses native libpq connection and TLS settings, including `PGHOST`, `PGPORT`, `PGUSER`, `PGDATABASE`, `PGSSLMODE`, and `PGSSLROOTCERT`. `PGHOST_FILE`, `PGPORT_FILE`, `PGUSER_FILE`, `PGDATABASE_FILE`, and `PGPASSWORD_FILE` read mounted secrets; a variable and its file alternative cannot both be set. Passwords are staged in a private temporary password file, removed after the native client exits. Commands are `dump OUTPUT`, `restore INPUT`, `basebackup DIRECTORY`, and `verify DIRECTORY`; native tool options can follow. All six tools can also be invoked by name through the wrapper. See `--help` for usage.

For example, with a prepared local output directory, password file, and trusted server CA:

```sh
docker run --rm --network database-network \
  --mount type=bind,src="$PWD/backups",dst=/backups \
  --mount type=bind,src="$PWD/backup-password",dst=/run/secrets/password,readonly \
  --mount type=bind,src="$PWD/server-ca.crt",dst=/run/secrets/server-ca,readonly \
  -e PGHOST=postgres -e PGUSER=backup -e PGDATABASE=app \
  -e PGPASSWORD_FILE=/run/secrets/password \
  -e PGSSLMODE=verify-full -e PGSSLROOTCERT=/run/secrets/server-ca \
  abruncloud/postgres:18-backup dump /backups/app.dump
```

Output defaults to root ownership. Use `--user` with pre-owned writable output storage to run unprivileged. Physical capture needs an authorized replication role, a matching replication authentication rule, and enough server WAL senders. Cancellation forwards signals to the native client process group, including its WAL streamer, and waits for client exit. Source-server work can continue until PostgreSQL detects disconnected clients; `wal_sender_timeout` does not bound every base-backup phase. Platforms requiring server-side quiescence must verify source sessions and apply authorized server-side cancellation separately. Scheduling, retention, and remote uploads belong to the caller.

Use the exact source major's tools for physical capture, WAL verification, and recovery. [`pg_verifybackup`](https://www.postgresql.org/docs/18/app-pgverifybackup.html) invokes its matching `pg_waldump` to parse the WAL required by a plain-format backup; the image includes both and the native tests exercise verification without skipping WAL. Verification does not prove recoverability: retain the originating runtime digest and test recovery into fresh storage with the required extensions. Newer `pg_dump` can support older servers, but that does not establish physical-backup or cross-major data-directory compatibility.

## Building and testing

From the repository root:

```sh
python3 tools/generate.py --check
docker build -f images/postgres/generated/18/trixie/Dockerfile -t postgres-runtime:test .
docker build -f images/postgres/generated/18/alpine3.24/Dockerfile -t postgres-alpine-runtime:test .
docker build -f images/postgres/generated/18/alpine3.24/Dockerfile.backup -t postgres-backup:test .
tests/run.sh postgres-runtime:test
tests/run.sh postgres-alpine-runtime:test
tests/run-backup.sh postgres-backup:test postgres-alpine-runtime:test
```

Runtime builds cover Debian and Alpine; the backup is built and qualified once per architecture against the Alpine runtime. The client can connect to PostgreSQL servers on either distribution. Generated Dockerfiles should not be edited directly: update templates or resolved inputs, then run `python3 tools/generate.py`. CI checks drift and runs native runtime tests for both distributions and Alpine backup/recovery tests for both supported architectures before publication. The backup harness verifies the client-only artifact boundary, verify-full TLS with file credentials, logical vector restoration, full physical/WAL verification with corrupted-WAL rejection, independent recovery with an actual HNSW index scan, and client cancellation followed by explicit fixture administrator cleanup.

## Updates and security

The privilege-dropping helper `gosu` is rebuilt from a checksum-pinned upstream source release and its locked module dependencies using a digest-pinned, security-patched Go compiler. The compiler runs only in a build stage with automatic toolchain downloads disabled; the runtime images receive the static helper and its license. Backup images contain client tools and do not need this privilege-dropping helper. Its version and compiler version appear in image labels and the input lock. PostgreSQL's official entrypoint remains unchanged. Rebuilding this helper reduces stale compiler findings; publication still requires rescanning the exact artifacts and passing the configured security gate.

Automated discovery proposes upstream patch, base-digest and pgvector changes. Publication follows the repository's checks and release policy; discovery does not update running containers. Major database upgrades and extension catalog upgrades require deliberate migration steps. Do not downgrade a data directory simply by selecting an older image.

See [SECURITY.md](../../SECURITY.md) for reporting vulnerabilities. This packaging includes software under separate upstream licenses; pgvector's license is included at `/usr/share/doc/pgvector/LICENSE` in the runtime image.
