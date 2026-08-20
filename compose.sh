#!/usr/bin/env bash
# Builds the subgraph, exports its SDL, and composes the Fusion gateway package.
# Re-run after changing the subgraph schema.
set -euo pipefail
cd "$(dirname "$0")"

dotnet tool restore
dotnet build Subgraph/Subgraph.csproj -v q --nologo

# Printing the schema from the built assembly keeps composition offline: no port to bind,
# and the SDL cannot drift from what the server actually serves.
(cd Subgraph/bin/Debug/net10.0 && dotnet Subgraph.dll print-schema) > Subgraph/schema/schema.graphql
echo "schema exported:"; sed -n '1,6p' Subgraph/schema/schema.graphql

dotnet tool run fusion subgraph pack -w Subgraph/schema -p Subgraph.fsp --allow-roll-forward
dotnet tool run fusion compose -s Subgraph.fsp -p gateway --settings compose-settings.json --allow-roll-forward

dotnet build Gateway/Gateway.csproj -v q --nologo
echo "gateway.fgp composed; run ./run-subgraph.sh and ./run-gateway.sh in separate terminals"
