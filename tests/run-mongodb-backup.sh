#!/usr/bin/env bash
set -euo pipefail
python3 tests/mongodb_backup_qualification.py "$@"
