#!/usr/bin/env bash

set -o errexit
set -o pipefail
set -o nounset

WHEELS_DIRECTORY=${WHEELS_DIRECTORY:-""}

echo "Wheels directory: $WHEELS_DIRECTORY"
if [ -n "$WHEELS_DIRECTORY" ]; then
  echo "Wheels directory contents:"
  ls -l "$WHEELS_DIRECTORY"
fi

PRE_FLAG=${PRE_FLAG:-""}
TARGET_VERSION=${TARGET_VERSION:-""}
MCP_GATEWAY_SOURCE="ubo-app-mcp-gateway${TARGET_VERSION:+==$TARGET_VERSION}"
BINDINGS_SOURCE="ubo-app-raw-bindings${TARGET_VERSION:+==$TARGET_VERSION}"
pip install $PRE_FLAG${WHEELS_DIRECTORY:+ --find-links="$WHEELS_DIRECTORY"} --prefer-binary "$MCP_GATEWAY_SOURCE" "$BINDINGS_SOURCE"
