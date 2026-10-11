#!/bin/sh
set -eu
umask 077
help() {
 cat <<'USAGE'
Usage: postgres-backup COMMAND [ARGS...]
  dump OUTPUT [pg_dump options...]             custom-format logical dump
  restore INPUT [pg_restore options...]        restore into PGDATABASE
  basebackup DIRECTORY [pg_basebackup options...]  physical backup with streamed WAL
  verify DIRECTORY [pg_verifybackup options...]    verify physical backup manifest
  pg_dump|pg_restore|pg_basebackup|pg_verifybackup|pg_waldump|psql [native options...]
Connection: standard libpq PGHOST, PGPORT, PGUSER, PGDATABASE and TLS settings.
PGHOST_FILE, PGPORT_FILE, PGUSER_FILE, PGDATABASE_FILE and PGPASSWORD_FILE
read private files. A variable and its _FILE equivalent cannot both be set.
All output remains local. This image does not start a database server.
USAGE
}
case "${1:-help}" in help|--help|-h) help; exit 0;; esac
for name in PGHOST PGPORT PGUSER PGDATABASE PGPASSWORD; do
 eval "file=\${${name}_FILE-}; present=\${${name}+set}"
 if test -n "$file"; then
  test "$present" != set || { echo "set either $name or ${name}_FILE" >&2; exit 2; }
  test -r "$file" || { echo "${name}_FILE is not readable" >&2; exit 2; }
  value=$(cat "$file")
  export "$name=$value"
 fi
done
command=$1
shift
case "$command" in
 dump|restore|basebackup|verify)
  test "$#" -ge 1 || { echo "$command requires a local path" >&2; exit 2; }
  target=$1; shift
  test -n "$target" && test "$target" != - || { echo "$command requires a local path" >&2; exit 2; }
  case "$command" in
   dump) test ! -e "$target" || { echo 'dump output already exists' >&2; exit 2; }; set -- pg_dump --format=custom --file="$target" "$@";;
   restore) test -r "$target" || { echo 'restore input is not readable' >&2; exit 2; }; set -- pg_restore --dbname="${PGDATABASE:-postgres}" "$@" "$target";;
   basebackup) set -- pg_basebackup --pgdata="$target" --format=plain --wal-method=stream --checkpoint=fast "$@";;
   verify) set -- pg_verifybackup "$@" "$target";;
  esac
  ;;
 pg_dump|pg_restore|pg_basebackup|pg_verifybackup|pg_waldump|psql) set -- "$command" "$@";;
 *) echo 'unsupported backup command; use help' >&2; exit 2;;
esac
scratch=$(mktemp -d /tmp/postgres-backup.XXXXXX)
child=
status=0
received_signal=
group=
cleanup(){ rm -rf "$scratch"; }
signal_child(){
 if test -n "$child"; then
  if test -n "$group"; then kill -s "$1" -- "-$child" 2>/dev/null || :; fi
  kill -s "$1" "$child" 2>/dev/null || :
 fi
}
forward(){ received_signal=$1; status=$2; signal_child "$1"; }
trap cleanup EXIT
trap 'forward TERM 143' TERM
trap 'forward INT 130' INT
trap 'forward HUP 129' HUP
trap 'forward QUIT 131' QUIT
if test "${PGPASSWORD+set}" = set; then
 newline='
'
 cr=$(printf '\r')
 case "$PGPASSWORD" in *"$newline"*|*"$cr"*) echo 'password must be a single line' >&2; exit 2;; esac
 escaped=$(printf '%s' "$PGPASSWORD" | sed 's/\\/\\\\/g;s/:/\\:/g')
 printf '*:*:*:*:%s\n' "$escaped" > "$scratch/pgpass"
 export PGPASSFILE="$scratch/pgpass"
 unset PGPASSWORD
fi
if test "$status" -ne 0; then exit "$status"; fi
# pg_basebackup forks a WAL streamer. A separate process group lets signals
# reach both native clients; signalling only its parent skips its atexit cleanup.
if command -v setsid >/dev/null 2>&1; then
 group=1
 setsid "$@" &
else
 "$@" &
fi
child=$!
if test "$status" -ne 0; then signal_child "$received_signal"; fi
# A signal can interrupt wait before the native tool has exited. Keep waiting
# so cancellation does not abandon an active client and cleanup runs afterward.
while :; do
 result=0
 wait "$child" || result=$?
 if ! kill -0 "$child" 2>/dev/null; then break; fi
done
if test "$status" -ne 0; then exit "$status"; fi
exit "$result"
