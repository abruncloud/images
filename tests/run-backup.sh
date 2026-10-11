#!/bin/sh
# Explicit native qualification: owns every named fixture and removes it on exit.
set -eu
backup_image=${1:?usage: run-backup.sh BACKUP_IMAGE SERVER_IMAGE}
server_image=${2:?usage: run-backup.sh BACKUP_IMAGE SERVER_IMAGE}
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
  -v "$logical:/logical" -v "$physical:/physical" "$backup_image" "$3" "$4"
}
run_backup backup postgres dump /logical/database.dump
docker exec "$source" createdb -U postgres logical_restored
run_backup postgres logical_restored restore /logical/database.dump
actual=$(docker exec "$source" psql -X -At -U postgres logical_restored -c "SELECT count(*),min(embedding <-> '[1,2,3]'::vector) FROM vectors")
test "$actual" = '1|0' || { echo 'logical vector restore failed' >&2; exit 1; }
run_backup backup postgres basebackup /physical/data
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
echo 'logical/vector restore, physical/vector recovery, manifest verification, client cancellation and fixture server cleanup passed'
