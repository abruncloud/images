#!/usr/bin/env python3
"""Turn upstream's shared server/checker executable into an unconditional checker."""
from pathlib import Path
import sys
path = Path(sys.argv[1])
source = path.read_text()
old = 'if (strstr(exec_name,"redis-check-rdb") != NULL)'
if source.count(old) != 1:
    raise SystemExit("Upstream checker dispatch changed; review required")
path.write_text(source.replace(old, 'if (1) /* Client-only build: never dispatch to the server. */'))
