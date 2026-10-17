#!/bin/sh
# Exact disposable fixtures; no published host ports or persistent user resources.
set -eu
backup=${1:?usage: run-mysql-backup.sh BACKUP_IMAGE RUNTIME_IMAGE}
runtime=${2:?usage: run-mysql-backup.sh BACKUP_IMAGE RUNTIME_IMAGE}
docker image inspect "$backup" | python3 -c 'import json,sys;c=json.load(sys.stdin)[0]["Config"];assert not c.get("Volumes");assert not c.get("ExposedPorts");assert not any(x.startswith("MYSQL_ROOT_PASSWORD=") for x in c.get("Env",[]))'
docker run --rm --entrypoint sh "$backup" -ec '
 for tool in mysql mysqldump mysqladmin mysqlbinlog;do "$tool" --version;done
 for tool in mysqld mysqld_safe mysql_install_db docker-entrypoint.sh;do ! command -v "$tool" >/dev/null 2>&1 || exit 1;done
 test ! -e /usr/sbin/mysqld;test ! -e /usr/local/bin/docker-entrypoint.sh
 for tool in setsid curl jq python3 tar gzip sha256sum wc sed;do command -v "$tool" >/dev/null;done
 ! rpm -qa | grep -E "mysql-community-server|mariadb" >/dev/null
'
prefix="mysql-backup-test-$(python3 -c 'import uuid;print(uuid.uuid4().hex[:12])')"
source="$prefix-source";destination="$prefix-restored";cancelled="$prefix-cancel";network="$prefix-network";output="$prefix-output";data="$prefix-source-data";restored="$prefix-restored-data"
secrets=$(mktemp -d)
cleanup(){ docker rm -fv "$cancelled" "$source" "$destination" >/dev/null 2>&1 || :;docker volume rm "$output" "$data" "$restored" >/dev/null 2>&1 || :;docker network rm "$network" >/dev/null 2>&1 || :;rm -rf "$secrets";}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
umask 077
python3 -c 'import secrets;print(secrets.token_hex(24))' > "$secrets/password"
printf '[client]\nuser=root\npassword="%s"\n' "$(cat "$secrets/password")" > "$secrets/admin.cnf"
docker network create "$network" >/dev/null
for volume in "$output" "$data" "$restored";do docker volume create "$volume" >/dev/null;done
admin(){ container=$1;shift;docker exec -i "$container" mysql --defaults-file=/run/secrets/admin.cnf --batch --skip-column-names "$@";}
ready(){ count=0;until printf 'SELECT 1;\n' | admin "$1" >/dev/null 2>&1;do count=$((count+1));test "$count" -lt 90 || { echo 'MySQL fixture not ready' >&2;exit 1;};sleep 1;done;}
start(){ 
 docker run -d --name "$1" --network "$network" --memory=1g --cpus=2 \
  -e MYSQL_ROOT_PASSWORD_FILE=/run/secrets/password -e MYSQL_ROOT_HOST=% -e MYSQL_DATABASE=app \
  -v "$secrets/password:/run/secrets/password:ro" -v "$secrets/admin.cnf:/run/secrets/admin.cnf:ro" \
  -v "$2:/var/lib/mysql" "$runtime" >/dev/null
 ready "$1"
 openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj "/CN=$1" -addext "subjectAltName=DNS:$1" \
  -keyout "$secrets/$1.key" -out "$secrets/$1.crt" >/dev/null 2>&1
 docker cp "$secrets/$1.key" "$1:/tmp/fixture.key" >/dev/null
 docker cp "$secrets/$1.crt" "$1:/tmp/fixture.crt" >/dev/null
 docker exec "$1" sh -ec 'cp /tmp/fixture.key /var/lib/mysql/server-key.pem;cp /tmp/fixture.crt /var/lib/mysql/server-cert.pem;chown mysql:mysql /var/lib/mysql/server-key.pem /var/lib/mysql/server-cert.pem;chmod 600 /var/lib/mysql/server-key.pem;rm /tmp/fixture.key /tmp/fixture.crt'
 printf 'ALTER INSTANCE RELOAD TLS;\n' | admin "$1" >/dev/null
}
start "$source" "$data"
start "$destination" "$restored"
cat <<'SQL' | admin "$source" app >/dev/null
CREATE TABLE entries(id INT PRIMARY KEY, value VARCHAR(50)) ENGINE=InnoDB;
CREATE TABLE audit_entries(id INT) ENGINE=InnoDB;
CREATE TRIGGER record_entry AFTER INSERT ON entries FOR EACH ROW INSERT INTO audit_entries VALUES(NEW.id);
INSERT INTO entries VALUES(1,'native-client-fixture');
CREATE VIEW entry_view AS SELECT id,value FROM entries;
CREATE PROCEDURE entry_count() SELECT COUNT(*) FROM entries;
CREATE EVENT scheduled_entry ON SCHEDULE EVERY 1 DAY DISABLE DO INSERT INTO entries VALUES(9,'event');
SQL
plugin=$(printf "SELECT plugin FROM mysql.user WHERE user='root' AND host='%%';\n" | admin "$source")
test "$plugin" = caching_sha2_password || { echo 'fixture must use caching_sha2_password' >&2;exit 1;}
client(){ host=$1;shift;docker run --rm --network "$network" --memory=512m --cpus=1 -e "MYSQL_HOST=$host" -e MYSQL_USER=root -e MYSQL_DATABASE=app \
 -e MYSQL_PASSWORD_FILE=/run/secrets/password -e MYSQL_SSL_MODE=VERIFY_IDENTITY -e MYSQL_SSL_CA=/run/secrets/ca.crt \
 -v "$secrets/password:/run/secrets/password:ro" -v "$secrets/$host.crt:/run/secrets/ca.crt:ro" -v "$output:/output" "$backup" "$@";}
tls=$(client "$source" mysql --batch --skip-column-names -e "SHOW SESSION STATUS LIKE 'Ssl_cipher'")
case "$tls" in *TLS*|*AES*|*CHACHA*) ;;*)echo 'verified TLS was not negotiated' >&2;exit 1;;esac
client "$source" dump /output/app.sql app
client "$destination" restore /output/app.sql app
status=0
client "$source" dump /output/missing.sql nonexistent_fixture_database >/dev/null 2>&1 || status=$?
test "$status" -ne 0 || { echo 'missing database capture unexpectedly succeeded' >&2;exit 1; }
docker run --rm --entrypoint sh -v "$output:/output" "$backup" -ec 'test ! -e /output/missing.sql;set -- /output/missing.sql.partial.*;test ! -e "$1"'

actual=$(printf 'SELECT CONCAT(id,":",value) FROM entry_view; CALL entry_count(); SELECT COUNT(*) FROM information_schema.EVENTS WHERE EVENT_SCHEMA="app"; INSERT INTO entries VALUES(2,"restored-trigger");SELECT COUNT(*) FROM audit_entries;\n' | admin "$destination" app)
expected=$(printf '1:native-client-fixture\n1\n1\n2')
test "$actual" = "$expected" || { echo 'restored data/view/routine/event/trigger mismatch' >&2;exit 1;}
# Hold a real schema metadata lock so mysqldump remains active during TERM.
printf 'LOCK TABLES app.entries WRITE;SELECT SLEEP(60);\n' | admin "$source" >/dev/null &
locker=$!
sleep 1
docker run -d --name "$cancelled" --network "$network" -e "MYSQL_HOST=$source" -e MYSQL_USER=root -e MYSQL_DATABASE=app \
 -e MYSQL_PASSWORD_FILE=/run/secrets/password -e MYSQL_SSL_MODE=VERIFY_IDENTITY -e MYSQL_SSL_CA=/run/secrets/ca.crt \
 -v "$secrets/password:/run/secrets/password:ro" -v "$secrets/$source.crt:/run/secrets/ca.crt:ro" -v "$output:/output" "$backup" dump /output/cancelled.sql app >/dev/null
count=0
while :;do
 active=$(printf "SELECT COUNT(*) FROM performance_schema.processlist WHERE USER='root' AND HOST NOT LIKE 'localhost%%' AND COMMAND<>'Sleep';\n" | admin "$source")
 test "$active" -gt 0 && break
 count=$((count+1));test "$count" -lt 30 || { echo 'capture not active' >&2;exit 1;};sleep 1
done
docker kill --signal=TERM "$cancelled" >/dev/null
status=$(docker wait "$cancelled");test "$status" = 143 || { echo 'cancel exit status mismatch' >&2;exit 1;}
docker run --rm --entrypoint sh -v "$output:/output" "$backup" -ec 'test ! -e /output/cancelled.sql;set -- /output/cancelled.sql.partial.*;test ! -e "$1"'
# MySQL may defer observing a disconnected client while its statement waits
# for our deliberate metadata lock. Release only that fixture lock holder first.
locker_id=$(printf "SELECT ID FROM performance_schema.processlist WHERE USER='root' AND HOST LIKE 'localhost%%' AND INFO='SELECT SLEEP(60)' LIMIT 1;\n" | admin "$source")
if test -n "$locker_id";then
 case "$locker_id" in *[!0-9]*) echo 'invalid fixture lock-holder identity' >&2;exit 1;;esac
 status=0
 printf 'KILL CONNECTION %s;\n' "$locker_id" | admin "$source" >/dev/null 2>"$secrets/locker-stop-error" || status=$?
 # An already-finished lock holder is safe; any other SQL error remains fatal.
 if test "$status" -ne 0 && ! grep -Eq '^ERROR 1094 \(HY000\)' "$secrets/locker-stop-error";then
  cat "$secrets/locker-stop-error" >&2;exit "$status"
 fi
fi
wait "$locker" 2>/dev/null || :
# Verify the cancelled capture leaves no remote connection after unblocking.
count=0
while :;do
 active=$(printf "SELECT COUNT(*) FROM performance_schema.processlist WHERE USER='root' AND HOST NOT LIKE 'localhost%%';\n" | admin "$source")
 test "$active" = 0 && break
 count=$((count+1));test "$count" -lt 30 || { echo 'cancelled client connection remained active after fixture unlock' >&2;exit 1;};sleep 1
done
status=0;docker run --rm "$backup" unsupported >/dev/null 2>&1 || status=$?;test "$status" = 2
echo 'MySQL client-only artifact, caching_sha2 authentication, verified TLS, native object restore, and atomic client cancellation passed'
