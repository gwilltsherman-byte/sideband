#!/bin/bash
set -euo pipefail
if curl --fail --silent http://localhost:8765/healthz >/dev/null; then exit 0; fi
nohup npm run serve >/tmp/sideband.log 2>&1 </dev/null &
