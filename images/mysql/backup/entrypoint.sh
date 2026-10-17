#!/bin/sh
set -eu
umask 077
fail(){ echo "$1" >&2; exit 2; }
case "${1:-help}" in help|-h|--help)
 cat <<'HELP'
Usage: mysql-backup dump OUTPUT [DATABASE]
       mysql-backup restore INPUT [DATABASE]
       mysql-backup mysql|mysqldump|mysqladmin|mysqlbinlog [OPTIONS...]
MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE and their
_FILE alternatives provide connection settings. MYSQL_SSL_MODE defaults to
VERIFY_IDENTITY; MYSQL_SSL_CA selects a mounted trusted CA. Output stays local.
Logical dumps require InnoDB tables and no concurrent DDL. No physical/PITR backup.
HELP
 exit 0;; esac
command=$1; shift
for name in MYSQL_HOST MYSQL_PORT MYSQL_USER MYSQL_PASSWORD MYSQL_DATABASE MYSQL_SSL_MODE MYSQL_SSL_CA; do
 eval "file=\${${name}_FILE-}; present=\${${name}+set}"
 if test -n "$file"; then
  test "$present" != set || fail "set either $name or ${name}_FILE"
  test -r "$file" || fail "${name}_FILE is not readable"
  value=$(cat "$file");export "$name=$value"
 fi
done
test "${MYSQL_PWD+set}" != set || fail 'MYSQL_PWD is unsupported; use MYSQL_PASSWORD_FILE'
output=;partial=;input=;database=
case "$command" in
 dump|restore)
  test "$#" -ge 1 && test "$#" -le 2 || fail "$command requires a local path and optional database"
  target=$1;shift
  test -n "$target" && test "$target" != - || fail 'a local path is required'
  database=${1:-${MYSQL_DATABASE:-}}
  case "$database" in ''|*[!A-Za-z0-9_]*|mysql|sys|performance_schema|information_schema) fail 'an application database name is required';; esac
  if test "$command" = dump; then
   test ! -e "$target" || fail 'dump output already exists'
   output=$target
  else
   test -r "$target" || fail 'restore input is not readable';input=$target
  fi;;
 mysql|mysqldump|mysqladmin|mysqlbinlog)
  for argument in "$@"; do
   case "$argument" in -p*|--password*|--defaults*|--login-path*) fail 'passwords and option files must not be supplied through command arguments';; esac
  done;;
 *) fail 'unsupported backup command; use help';;
esac
scratch=$(mktemp -d /tmp/mysql-backup.XXXXXX)
child=;status=0;received=
cleanup(){ test -z "$partial" || rm -f "$partial";rm -rf "$scratch"; }
signal_child(){ if test -n "$child"; then kill -s "$1" -- "-$child" 2>/dev/null || :;kill -s "$1" "$child" 2>/dev/null || :;fi; }
forward(){ received=$1;status=$2;signal_child "$1"; }
trap cleanup EXIT
trap 'forward TERM 143' TERM
trap 'forward INT 130' INT
trap 'forward HUP 129' HUP
trap 'forward QUIT 131' QUIT
printf '[client]\nprotocol=TCP\n' > "$scratch/options.cnf"
option(){
 value=$2
 newline='
'
 cr=$(printf '\r')
 case "$value" in *"$newline"*|*"$cr"*) fail 'connection values must be single lines';; esac
 escaped=$(printf '%s' "$value" | sed 's/\\/\\\\/g;s/"/\\"/g')
 printf '%s="%s"\n' "$1" "$escaped" >> "$scratch/options.cnf"
}
option host "${MYSQL_HOST:-localhost}"
option port "${MYSQL_PORT:-3306}"
option user "${MYSQL_USER:-root}"
if test "${MYSQL_PASSWORD+set}" = set; then option password "$MYSQL_PASSWORD";fi
option ssl-mode "${MYSQL_SSL_MODE:-VERIFY_IDENTITY}"
if test -n "${MYSQL_SSL_CA:-}"; then option ssl-ca "$MYSQL_SSL_CA";fi
unset MYSQL_PASSWORD MYSQL_PWD
case "$command" in
 dump) set -- mysqldump "--defaults-file=$scratch/options.cnf" --no-login-paths --single-transaction --quick --routines --events --triggers --no-tablespaces --set-gtid-purged=OFF -- "$database";;
 restore) set -- mysql "--defaults-file=$scratch/options.cnf" --no-login-paths "$database";;
 *) set -- "$command" "--defaults-file=$scratch/options.cnf" --no-login-paths "$@";;
esac
test "$status" = 0 || exit "$status"
if test -n "$output";then partial=$(mktemp "$output.partial.XXXXXX");fi
if test -n "$output"; then setsid "$@" > "$partial" &
elif test -n "$input"; then setsid "$@" < "$input" &
else setsid "$@" &
fi
child=$!
if test "$status" != 0;then signal_child "$received";fi
while :; do result=0;wait "$child" || result=$?;kill -0 "$child" 2>/dev/null || break;done
test "$status" = 0 || exit "$status"
test "$result" = 0 || exit "$result"
if test -n "$output";then
 # Atomic, same-filesystem publication with no overwrite if a competing file appeared.
 ln "$partial" "$output" || exit 1
 rm -f "$partial";partial=
fi
exit 0
