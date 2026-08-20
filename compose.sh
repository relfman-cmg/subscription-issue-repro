#!/usr/bin/env bash
# Builds the subgraph, exports its SDL, and composes the Fusion archive.
# Re-run after changing the subgraph schema.
set -euo pipefail
cd "$(dirname "$0")"

dotnet tool restore
dotnet build Subgraph/Subgraph.csproj -v q --nologo

# The filename stem must match the settings file beside it (Subgraph.graphqls -> Subgraph-settings.json);
# the CLI derives the settings path from the schema path and fails if it is missing.
# The trailing echo adds the final newline the SDL printer omits, so re-running this is idempotent.
{ (cd Subgraph/bin/Debug/net10.0 && dotnet Subgraph.dll print-schema); echo; } > Subgraph/schema/Subgraph.graphqls
echo "schema exported:"; sed -n '1,6p' Subgraph/schema/Subgraph.graphqls

# v16 composes in one step: no `subgraph pack`, no .fsp intermediate.
dotnet tool run fusion --allow-roll-forward -- compose -s Subgraph/schema/Subgraph.graphqls -f gateway.far

dotnet build Gateway/Gateway.csproj -v q --nologo
echo "gateway.far composed; run ./run-subgraph.sh and ./run-gateway.sh in separate terminals"
