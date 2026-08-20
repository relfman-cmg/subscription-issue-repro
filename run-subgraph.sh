#!/usr/bin/env bash
# TICK_SECONDS=0 emits no events at all — the client then sees only gateway pings.
set -euo pipefail
cd "$(dirname "$0")/Subgraph/bin/Debug/net10.0"
exec dotnet Subgraph.dll
