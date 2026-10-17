#!/bin/sh
set -eu
umask 077
if [ "${1#-}" != "$1" ]; then set -- clickhouse-sql "$@"; fi
exec "$@"
