#!/usr/bin/env bash
set -Eeuo pipefail

image=${1:?Usage: tests/run.sh IMAGE}
task_name="images-postgres-test-$(date +%s)-$$"
container="${task_name}-server"
volume="${task_name}-data"
test_dir=$(mktemp -d)
cleanup() {
  docker rm -fv "$container" >/dev/null 2>&1 || true
  docker volume rm "$volume" >/dev/null 2>&1 || true
  rm -rf "$test_dir"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
chmod 755 "$test_dir"
printf '%s\n' 'integration-test-password' > "$test_dir/password"
printf '%s\n' 'CREATE TABLE initialized(value text); INSERT INTO initialized VALUES ('"'"'sql'"'"');' > "$test_dir/10-init.sql"
cat > "$test_dir/20-init.sh" <<'SCRIPT'
#!/usr/bin/env bash
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -c "INSERT INTO initialized VALUES ('shell');"
SCRIPT
printf "%s\n" "listen_addresses = '*'" 'max_connections = 37' 'shared_preload_libraries = '''pg_stat_statements'''' > "$test_dir/postgresql.conf"
chmod 644 "$test_dir/password" "$test_dir/10-init.sql" "$test_dir/postgresql.conf"
chmod 755 "$test_dir/20-init.sh"
docker volume create --label org.abruncloud.test=postgres "$volume" >/dev/null
start() {
  docker run -d --name "$container" --label org.abruncloud.test=postgres \
    "$@" \
    -e POSTGRES_USER=tester -e POSTGRES_DB=app \
    -e POSTGRES_PASSWORD_FILE=/run/secrets/password \
    -v "$test_dir/password:/run/secrets/password:ro" \
    -v "$test_dir/10-init.sql:/docker-entrypoint-initdb.d/10-init.sql:ro" \
    -v "$test_dir/20-init.sh:/docker-entrypoint-initdb.d/20-init.sh:ro" \
    -v "$test_dir/postgresql.conf:/etc/postgresql/test.conf:ro" \
    -v "$volume:/var/lib/postgresql" \
    "$image" postgres -c config_file=/etc/postgresql/test.conf >/dev/null
}
wait_ready() {
  for _ in $(seq 1 90); do
    if docker exec -e PGPASSWORD=integration-test-password "$container" psql -h 127.0.0.1 -U tester -d app -Atqc 'SELECT count(*) FROM initialized' 2>/dev/null | grep -qx 2; then
      return
    fi
    sleep 1
  done
  docker logs "$container"
  echo 'PostgreSQL failed to initialize' >&2
  return 1
}
sql() {
  docker exec -i "$container" psql -v ON_ERROR_STOP=1 -U tester -d app "$@"
}
start
wait_ready
test "$(sql -Atqc 'SHOW max_connections')" = 37
test "$(docker exec "$container" sh -c 'ps -o user= -p 1' 2>/dev/null | tr -d ' ')" = postgres || \
  docker exec "$container" sh -c 'test "$(id -u postgres)" = "$(awk '\''/^Uid:/ {print $2}'\'' /proc/1/status)"'
sql <<'SQL'
CREATE EXTENSION vector;
CREATE EXTENSION pg_trgm;
CREATE EXTENSION pgcrypto;
CREATE EXTENSION pg_stat_statements;
CREATE EXTENSION "uuid-ossp";
CREATE EXTENSION btree_gin;
CREATE EXTENSION btree_gist;
CREATE TABLE embeddings(id integer PRIMARY KEY, embedding vector(3));
INSERT INTO embeddings VALUES (1, '[1,2,3]'), (2, '[4,5,6]');
CREATE INDEX embeddings_hnsw ON embeddings USING hnsw (embedding vector_l2_ops);
CREATE INDEX embeddings_ivfflat ON embeddings USING ivfflat (embedding vector_l2_ops) WITH (lists=1);
SQL
test "$(sql -Atqc "SELECT id FROM embeddings ORDER BY embedding <-> '[1,2,3]' LIMIT 1")" = 1
# Use the container network address: upstream trusts loopback connections.
server_address=$(docker inspect -f "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}" "$container")
docker exec -e PGPASSWORD=integration-test-password "$container" \
  psql -h "$server_address" -U tester -d app -v ON_ERROR_STOP=1 -Atqc 'SELECT 1' | grep -qx 1
if docker exec -e PGPASSWORD=wrong-password "$container" \
  psql -h "$server_address" -U tester -d app -Atqc 'SELECT 1' >/dev/null 2>&1; then
  echo 'Wrong password was accepted' >&2
  exit 1
fi
docker stop -t 30 "$container" >/dev/null
test "$(docker inspect -f '{{.State.ExitCode}}' "$container")" = 0
docker rm "$container" >/dev/null
# Reuse existing data as the database user; init scripts must not run twice.
start --user postgres
wait_ready
test "$(sql -Atqc 'SELECT count(*) FROM embeddings')" = 2
docker stop -t 30 "$container" >/dev/null
test "$(docker inspect -f '{{.State.ExitCode}}' "$container")" = 0
printf 'Runtime tests passed: %s\n' "$image"
