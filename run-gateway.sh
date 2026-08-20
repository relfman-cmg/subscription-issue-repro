#!/usr/bin/env bash
set -euo pipefail

# The default appsettings.json file-watcher recurses until the stack overflows on some
# filesystems (tmpfs, container overlays), killing the process inside CreateBuilder.
export DOTNET_hostBuilder__reloadConfigOnChange=false
cd "$(dirname "$0")/Gateway/bin/Debug/net10.0"
exec dotnet Gateway.dll
