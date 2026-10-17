#!/usr/bin/env bash
set -euo pipefail
python3 tests/clickhouse_backup_qualification.py "$@"
