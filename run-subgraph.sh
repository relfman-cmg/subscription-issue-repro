#!/usr/bin/env bash
# Silent by default — the client sees only gateway pings. TICK_SECONDS=5 emits a tick every 5s.
set -euo pipefail
cd "$(dirname "$0")/Subgraph/bin/Debug/net10.0"
exec dotnet Subgraph.dll
