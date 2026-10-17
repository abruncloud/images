# ClickHouse client-only backup tools

`abruncloud/clickhouse` contains a generic native TLS SQL client and archive tools,
not a ClickHouse server. The reviewed compatibility line is ClickHouse 26.8 LTS;
the initial native fixture is the pinned Docker Official 26.8.28.14 Jammy image.

## Tags and versions

Aliases are `26.8.28.14-backup`, `26.8-backup`,
`26.8.28.14-alpine3.22-backup` and `26.8-alpine3.22-backup`. The version is the
**qualified server/archive compatibility version**, not the client driver version.
The executable reports `clickhouse-sql 1.0.0 (official clickhouse-go/v2 2.49.0)`.
Production users should pin a signed release index digest. New aliases never move
existing instances. Only backup images are published; Docker Hub has no temporary
build tags. First publication is gated on native amd64/arm64 and security checks.

Upstream's `clickhouse-client` uses the same common-static executable as the
server. Copying it into a small image would still carry server dispatch. Instead,
`clickhouse-sql` uses ClickHouse's official Go native driver, pinned with all module
checksums. There is no server executable, server implementation or C++ build here.
This small tool intentionally has its own name and supports one SQL statement;
it does not promise the full interactive `clickhouse-client` interface.

## Connection and commands

Supply a private XML connection file; passwords are never command-line arguments:

```xml
<config>
  <host>database.example.com</host><port>9440</port>
  <user>backup</user><password>replace-and-escape-XML</password>
  <database>default</database><secure>true</secure>
  <openSSL><client>
    <caConfig>/run/secrets/database-ca</caConfig>
    <verificationMode>strict</verificationMode>
  </client></openSSL>
</config>
```

```sh
docker run --rm --network your-private-network \
  --mount type=bind,src="$PWD/connection.xml",dst=/run/secrets/connection.xml,readonly \
  --mount type=bind,src="$PWD/ca.pem",dst=/run/secrets/database-ca,readonly \
  abruncloud/clickhouse:26.8.28.14-backup \
  clickhouse-sql --config-file=/run/secrets/connection.xml \
  --query 'SELECT version() FORMAT TSVRaw'
```

`--query_id` sets a caller-owned operation identity, and `--timeout=30s` bounds
execution (maximum 1h). Output is raw tab-separated scalars with a newline per row,
bounded at 8 MiB. Requests use a 10-second dial deadline and the execution deadline
also bounds reads. CA validation and hostname/IP identity checks are mandatory;
`secure=false` and verification bypasses are rejected. An optional XML
`openSSL.client.serverName` overrides the verified TLS identity for private DNS.
SIGTERM/INT cancels the active driver context and exits unsuccessfully. An absent
client process does not prove server-side backup termination: observe
`system.backups`, and use the same account to cancel its owned query before
releasing a backup fence. Never publish a partial or unverified archive.

## Native archives and restoration

`BACKUP DATABASE default TO Disk('backups','snapshot.zip')` asks the **server** to
write an archive to a server-configured, allowed backup disk. A client path is not
a server path. Supply a shared protected staging mount when collecting the archive,
or configure an explicitly allowed remote backup destination. This generic image
does not create server disks, provision users, embed cloud credentials or contain
Abrun job scripts. Use least-privilege backup and restore principals. Restores are
operator actions against a compatible server; server upgrades and cross-version
archive restoration need separate qualification.

The image supplies curl, jq, Python 3, tar, gzip, zip/unzip, coreutils, setsid,
setpriv, CA roots and tini. Default UID/GID is 10001 with `/backup` mode0700.
The working directory is `/`, so an explicitly selected alternate UID can start
without entering the private default backup directory. Mount permissions must allow that UID. The entrypoint sets umask077 and runs under
tini process-group forwarding; flags are passed to `clickhouse-sql`. No credentials
or ports are embedded, and the image can run with all capabilities dropped and
no-new-privileges. A platform may explicitly prepare its own staging directory
as root and drop privileges before starting its mounted job.

## Updates and release gates

Discovery follows the reviewed 26.8 LTS Jammy server fixture, Alpine3.22 runtime
and Go1.27 Bookworm compiler patch line. Driver/tool/distribution/major changes
require review. Every input update goes through real pull-request native checks;
GitHub may require a maintainer to approve bot-created workflows. No dispatch or
administrator bypass substitutes for those checks. Daily builds upgrade all
installed Alpine packages before adding tools, qualify both native architectures,
scan the exact native candidate and apply the shared actionable security policy.
Complete reports, SBOM/provenance, signed digest and durable release input records
accompany promotion. Runtime compiler packages are absent. Tool source is MIT;
the official driver is Apache2.0, and dependency license notices ship in the image.
