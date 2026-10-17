#!/bin/sh
set -eu
umask 077
if [ "$#" -eq 0 ]; then set -- mongodump --help; fi
case "$1" in -*) set -- mongodump "$@" ;; esac
exec "$@"
