#!/bin/sh
# Explicit native qualification: owns every named fixture and removes it on exit.
set -eu
backup_image=${1:?usage: run-backup.sh BACKUP_IMAGE SERVER_IMAGE}
server_image=${2:?usage: run-backup.sh BACKUP_IMAGE SERVER_IMAGE}
# A backup artifact is independently packaged: no server binaries or inherited
# runtime initialization, persistence, or network metadata.
docker image inspect "$backup_image" | python3 -c 'import json,sys; c=json.load(sys.stdin)[0]["Config"]; assert not c.get("Volumes"),"backup declares persistent volumes"; assert not c.get("ExposedPorts"),"backup exposes ports"; assert not any(v.startswith("PGDATA=") for v in c.get("Env",[])),"backup inherits PGDATA"'
docker run --rm --entrypoint sh "$backup_image" -ec '
 for binary in postgres initdb pg_ctl docker-entrypoint.sh; do
  if command -v "$binary" >/dev/null 2>&1; then echo "unexpected server command: $binary" >&2; exit 1; fi
 done
 test ! -e /usr/local/bin/docker-entrypoint.sh
 for path in /usr/lib/postgresql/*/bin/postgres /usr/lib/postgresql/*/bin/initdb /usr/lib/postgresql/*/bin/pg_ctl /usr/local/bin/postgres /usr/local/bin/initdb /usr/local/bin/pg_ctl; do
  test ! -e "$path" || { echo "unexpected server executable: $path" >&2;exit 1; }
 done
 for binary in pg_dump pg_restore pg_basebackup pg_verifybackup psql pg_waldump; do "$binary" --version; done
 for binary in sh setsid mktemp sed cat rm; do command -v "$binary" >/dev/null; done
'
# Control-plane capture scripts require both tools in the client-only artifact.
docker run --rm --entrypoint sh "$backup_image" -ec '
 curl --version >/dev/null
 test "$(printf true | jq -r .)" = true
'
prefix="postgres-backup-test-$(python3 -c 'import uuid;print(uuid.uuid4().hex[:12])')"
network="$prefix-network"
source="$prefix-source"
recovered="$prefix-recovered"
cancelled="$prefix-cancel"
logical="$prefix-logical"
physical="$prefix-physical"
cancel_volume="$prefix-cancel-output"
source_volume="$prefix-source-data"
secrets=$(mktemp -d)
cleanup(){
 docker rm -fv "$cancelled" "$recovered" "$source" >/dev/null 2>&1 || :
 docker volume rm "$logical" "$physical" "$cancel_volume" "$source_volume" >/dev/null 2>&1 || :
 docker network rm "$network" >/dev/null 2>&1 || :
 rm -rf "$secrets"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
umask 077
python3 -c 'import secrets;print(secrets.token_hex(24))' > "$secrets/password"
password=$(cat "$secrets/password")
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj "/CN=$source" \
 -addext "subjectAltName=DNS:$source" -keyout "$secrets/server.key" \
 -out "$secrets/server.crt" >/dev/null 2>&1
docker network create "$network" >/dev/null
for volume in "$logical" "$physical" "$cancel_volume" "$source_volume"; do docker volume create "$volume" >/dev/null; done
docker run -d --name "$source" --network "$network" --memory=1g --cpus=2 \
 -e POSTGRES_PASSWORD_FILE=/run/secrets/password -e PGDATA=/data \
 -v "$secrets/password:/run/secrets/password:ro" -v "$source_volume:/data" \
 "$server_image" postgres -c wal_level=replica -c max_wal_senders=10 >/dev/null
ready(){
 count=0
 until docker exec "$1" pg_isready -h 127.0.0.1 -U postgres >/dev/null 2>&1; do
  count=$((count+1)); test "$count" -lt 60 || { echo 'fixture did not become ready' >&2; exit 1; }; sleep 1
 done
}
ready "$source"
docker cp "$secrets/server.key" "$source:/tmp/server.key" >/dev/null
docker cp "$secrets/server.crt" "$source:/tmp/server.crt" >/dev/null
docker exec "$source" sh -ec 'cp /tmp/server.key /tmp/server.crt "$PGDATA/"; chown postgres:postgres "$PGDATA/server.key" "$PGDATA/server.crt"; chmod 600 "$PGDATA/server.key"; rm /tmp/server.key /tmp/server.crt'
docker exec "$source" psql -X -q -v ON_ERROR_STOP=1 -U postgres postgres -c "ALTER SYSTEM SET ssl='on'" >/dev/null
docker exec "$source" psql -X -q -v ON_ERROR_STOP=1 -U postgres postgres -c "ALTER SYSTEM SET ssl_cert_file='server.crt'" >/dev/null
docker exec "$source" psql -X -q -v ON_ERROR_STOP=1 -U postgres postgres -c "ALTER SYSTEM SET ssl_key_file='server.key'" >/dev/null
docker restart "$source" >/dev/null
ready "$source"
# Generated alphanumeric password is sent over stdin, never Docker/psql argv.
printf "CREATE EXTENSION vector; CREATE TABLE vectors(id integer PRIMARY KEY, embedding vector(3)); INSERT INTO vectors VALUES(1,'[1,2,3]'); CREATE INDEX vectors_hnsw ON vectors USING hnsw(embedding vector_l2_ops); CREATE ROLE backup LOGIN REPLICATION PASSWORD '%s'; GRANT pg_read_all_data TO backup;\n" "$password" | docker exec -i "$source" psql -X -q -v ON_ERROR_STOP=1 -U postgres postgres
unset password
# The official initial host rule intentionally excludes replication; enable only
# this disposable test role on the isolated fixture network.
docker exec "$source" sh -c 'printf "%s\n" "host replication backup 0.0.0.0/0 scram-sha-256" >> "$PGDATA/pg_hba.conf"'
docker exec "$source" psql -X -q -U postgres postgres -c 'SELECT pg_reload_conf()' >/dev/null
run_backup(){
 docker run --rm --network "$network" --memory=512m --cpus=1 \
  -e "PGHOST=$source" -e PGPORT=5432 -e "PGUSER=$1" -e "PGDATABASE=$2" \
  -e PGPASSWORD_FILE=/run/secrets/password -v "$secrets/password:/run/secrets/password:ro" \
  -e PGSSLMODE=verify-full -e PGSSLROOTCERT=/run/secrets/server-ca \
  -v "$secrets/server.crt:/run/secrets/server-ca:ro" \
  -v "$logical:/logical" -v "$physical:/physical" "$backup_image" "$3" "$4"
}
tls=$(docker run --rm --network "$network" -e "PGHOST=$source" -e PGUSER=backup -e PGDATABASE=postgres \
 -e PGPASSWORD_FILE=/run/secrets/password -v "$secrets/password:/run/secrets/password:ro" \
 -e PGSSLMODE=verify-full -e PGSSLROOTCERT=/run/secrets/server-ca -v "$secrets/server.crt:/run/secrets/server-ca:ro" \
 "$backup_image" psql -X -qAt -c 'SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()')
test "$tls" = t || { echo 'verified TLS connection required' >&2;exit 1; }
run_backup backup postgres dump /logical/database.dump
docker exec "$source" createdb -U postgres logical_restored
run_backup postgres logical_restored restore /logical/database.dump
actual=$(docker exec "$source" psql -X -At -U postgres logical_restored -c "SELECT count(*),min(embedding <-> '[1,2,3]'::vector) FROM vectors")
test "$actual" = '1|0' || { echo 'logical vector restore failed' >&2; exit 1; }
run_backup backup postgres basebackup /physical/data
run_backup backup postgres verify /physical/data
# WAL parsing is mandatory: corrupt a required segment, verify rejection, restore
# the byte-for-byte original before attempting independent server recovery.
docker run --rm --entrypoint sh -v "$physical:/physical" -v "$logical:/logical" "$backup_image" -ec '
 for wal in /physical/data/pg_wal/*; do
  name=${wal##*/}
  if test -f "$wal" && test "${#name}" = 24; then
   cp "$wal" /logical/original-wal
   printf "%s" "$name" > /logical/wal-name
   blocks=$(($(wc -c < "$wal") / 1024))
   dd if=/dev/zero of="$wal" bs=1024 count="$blocks" conv=notrunc 2>/dev/null
   exit 0
  fi
 done
 echo "physical backup contains no WAL segment" >&2;exit 1
'
status=0
run_backup backup postgres verify /physical/data >/dev/null 2>&1 || status=$?
test "$status" -ne 0 || { echo 'corrupted WAL was accepted' >&2;exit 1; }
docker run --rm --entrypoint sh -v "$physical:/physical" -v "$logical:/logical" "$backup_image" -ec 'name=$(cat /logical/wal-name); cp /logical/original-wal "/physical/data/pg_wal/$name"'
run_backup backup postgres verify /physical/data
docker run -d --name "$recovered" --network "$network" --memory=1g --cpus=2 \
 -e PGDATA=/physical/data -v "$physical:/physical" "$server_image" postgres >/dev/null
ready "$recovered"
actual=$(docker exec "$recovered" psql -X -At -U postgres postgres -c "SELECT count(*),min(embedding <-> '[1,2,3]'::vector),(SELECT count(*) FROM pg_indexes WHERE indexname='vectors_hnsw') FROM vectors")
test "$actual" = '1|0|1' || { echo 'physical vector recovery failed' >&2; exit 1; }
plan=$(docker exec "$recovered" psql -X -qAt -U postgres postgres -c "SET enable_seqscan=off; EXPLAIN SELECT id FROM vectors ORDER BY embedding <-> '[1,2,3]'::vector LIMIT 1")
case "$plan" in *'Index Scan using vectors_hnsw'*) ;; *) echo 'recovered HNSW index was not usable' >&2;exit 1;; esac
actual=$(docker exec "$recovered" psql -X -qAt -U postgres postgres -c "SET enable_seqscan=off; SELECT id,embedding <-> '[1,2,3]'::vector FROM vectors ORDER BY embedding <-> '[1,2,3]'::vector LIMIT 1")
test "$actual" = '1|0' || { echo 'recovered HNSW nearest result mismatch' >&2;exit 1; }
# Keep a real physical capture in progress, then verify wrapper signal forwarding
# and its exit status. Client termination does not guarantee immediate server
# quiescence in every base-backup phase; the fixture explicitly ends only its
# identified backup connections, then verifies that source work has stopped.
docker run -d --name "$cancelled" --network "$network" --memory=512m --cpus=1 \
 -e "PGHOST=$source" -e PGUSER=backup -e PGAPPNAME=backup-cancel-qualification \
 -e PGPASSWORD_FILE=/run/secrets/password -v "$secrets/password:/run/secrets/password:ro" \
  -e PGSSLMODE=verify-full -e PGSSLROOTCERT=/run/secrets/server-ca \
  -v "$secrets/server.crt:/run/secrets/server-ca:ro" \
 -v "$cancel_volume:/output" "$backup_image" basebackup /output/data --max-rate=32k >/dev/null
count=0
while :; do
 active=$(docker exec "$source" psql -X -At -U postgres postgres -c "SELECT count(*) FROM pg_stat_activity WHERE application_name='backup-cancel-qualification'")
 test "$active" -gt 0 && break
 count=$((count+1));test "$count" -lt 30 || { echo 'capture did not become active' >&2;exit 1; };sleep 1
done
docker kill --signal=TERM "$cancelled" >/dev/null
status=$(docker wait "$cancelled")
test "$status" = 143 || { echo 'signal exit status was not preserved' >&2; exit 1; }
# This is fixture administrator cleanup, not a privileged feature of the image.
docker exec "$source" psql -X -qAt -v ON_ERROR_STOP=1 -U postgres postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE application_name='backup-cancel-qualification' AND usename='backup' AND backend_type='walsender'" >/dev/null
count=0
while :; do
 active=$(docker exec "$source" psql -X -At -U postgres postgres -c "SELECT count(*) FROM pg_stat_activity WHERE application_name='backup-cancel-qualification'")
 test "$active" = 0 && break
 count=$((count+1));test "$count" -lt 30 || { echo 'source capture connection remains active' >&2; docker exec "$source" psql -X -At -U postgres postgres -c "SELECT backend_type,state,wait_event_type,wait_event FROM pg_stat_activity WHERE application_name='backup-cancel-qualification'" >&2;exit 1; };sleep 1
done
status=0
docker run --rm "$backup_image" unsupported-command >/dev/null 2>&1 || status=$?
test "$status" = 2 || { echo 'unsupported command did not return2' >&2; exit 1; }
echo 'logical/vector restore, physical/vector recovery, TLS, WAL corruption rejection, manifest verification, client cancellation and fixture server cleanup passed'
