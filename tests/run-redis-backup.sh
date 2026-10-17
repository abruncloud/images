#!/bin/bash
set -euo pipefail
exec python3 "$(dirname "$0")/redis_backup_qualification.py" "$@"
