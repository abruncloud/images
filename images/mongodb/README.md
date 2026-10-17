# MongoDB backup tools

`abruncloud/mongodb` contains client tools only. It does not contain `mongod`, `mongos`, or `mongosh`, and cannot start a database server. Use the Docker Official `mongo` image for the server. No Abrun credentials, provisioning scripts, storage destinations or scheduled jobs are baked into this image.

## Supported tags

The first qualified line is MongoDB 8.0, with Database Tools **100.19.1** and one Ubuntu 24.04 (`noble`) runtime on native `linux/amd64` and `linux/arm64`.

| Tags | Meaning |
| --- | --- |
| `8.0.34-backup`, `8.0.34-noble-backup` | Qualified against server 8.0.34; rebuildable security aliases |
| `8.0-backup`, `8.0-noble-backup` | Latest qualified image for the reviewed 8.0 server line |

Database Tools have independent 100.x versions. A backup tag identifies the tested server compatibility line; `versions.lock.json` records the exact tools release, per-architecture HTTPS archive SHA256 and official base manifest. Existing platform instances pin the released image digest. No `latest`, server, temporary `build-*` or distribution variants beyond Noble are published to Docker Hub.

Ubuntu is intentional: MongoDB publishes and supports the official tools for Ubuntu 24.04 on both architectures. It does not publish supported Alpine/musl archives. The image also supplies Python3 with Ubuntu's maintained PyMongo and YAML packages, curl, jq, tar, gzip, tini and setpriv for generic backup orchestration.

## Remote archive and recovery

Default user/group is `10001:10001`, with `tini -g` as PID1 and an entrypoint that sets `umask 077` then executes the requested command. Create a writable workspace owned by this UID. Mount secrets read-only and allow only that UID to read the secrets in your deployment.

A private `dump.yml` can contain:

```yaml
uri: mongodb://backup@database:27017/?authSource=admin&directConnection=true
password: replace-in-the-private-file
```

Run a complete replica-set backup:

```sh
docker run --rm --network database \
  --mount type=bind,src="$PWD/dump.yml",dst=/run/secrets/dump.yml,readonly \
  --mount type=bind,src="$PWD/backup",dst=/backup \
  abruncloud/mongodb:8.0-backup \
  mongodump --config=/run/secrets/dump.yml \
  --archive=/backup/database.archive.gz --gzip --oplog
```

`--oplog` requires a replica set, a complete dump and permission to read the oplog. It cannot be combined with `--db`. A plain standalone dump is not a consistent snapshot while writes continue. The producer must reject unsupported topology, oplog rollover or incompatible operations instead of claiming consistency. This image does not impose a deployment topology or silently omit `--oplog`.

Restore into a compatible server with the same major version or feature compatibility version using a private restore config:

```sh
mongorestore --config=/run/secrets/restore.yml \
  --archive=/backup/database.archive.gz --gzip --oplogReplay
```

`--drop` is deliberately omitted from this example because it deletes target collections. Recovery is an explicit operator action. Preserve the archive SHA256, source server/tools versions, FCV, topology and restore instructions beside each backup. Upload archives from the backup job using short-lived presigned URLs; no S3 keys are needed by the database server or image.

## Qualification and updates

`tests/run-mongodb-backup.sh` runs against the exact pinned official MongoDB server on each native runner. It proves authenticated replica-set archive and oplog replay into fresh storage, BSON types/Unicode, indexes/views, restart persistence, wrong-credential and corrupt-archive rejection, nonroot operation, server binary absence and bounded signal termination of the real dump client. Every fixture is removed in a `finally` block.

The discovery workflow checks the official `mongo` image tag feed, MongoDB's tools release/checksum feed and official Ubuntu manifest. It creates a reviewable lock/recipe change. New server release lines, tools minor lines or distribution changes require review. Routine patches use the existing protected PR flow; native tests and the actionable vulnerability policy must pass before publication. Daily rebuilds refresh supported OS packages; daily rescans retain all vulnerability findings. Native candidates are kept in GHCR. Only tested, scanned and signed digests are copied to Docker Hub, with SBOM/provenance and a durable release record.

## Licenses and sources

MongoDB Database Tools are [Apache-2.0](https://github.com/mongodb/mongo-tools/blob/master/LICENSE.md). Their official archive license/notice files are retained in `/usr/share/licenses/mongodb-database-tools/`; installed Ubuntu packages retain their own copyright notices. The SSPL MongoDB server is not redistributed in this image.

- [Database Tools compatibility and supported platforms](https://www.mongodb.com/docs/database-tools/mongodump/mongodump-compatibility-and-installation/)
- [Official tools release/checksum feed](https://fastdl.mongodb.org/tools/db/release.json)
- [mongodump consistency and oplog restrictions](https://www.mongodb.com/docs/database-tools/mongodump/)
- [mongorestore compatibility and oplog replay](https://www.mongodb.com/docs/database-tools/mongorestore/)
