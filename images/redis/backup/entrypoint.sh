#!/bin/sh
set -eu
umask 077
if [ "$#" -eq 0 ]; then set -- redis-cli --help; fi
case "$1" in -*) set -- redis-cli "$@" ;; esac
exec "$@"
