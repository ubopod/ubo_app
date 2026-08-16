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

# No --pre: the `==$TARGET_VERSION` pins below already opt these two internal
# packages into pre-releases. A global --pre would also let third-party
# transitive dependencies resolve to betas.
TARGET_VERSION=${TARGET_VERSION:-""}
ASSISTANT_SOURCE="ubo-app-assistant${TARGET_VERSION:+==$TARGET_VERSION}"
BINDINGS_SOURCE="ubo-app-raw-bindings${TARGET_VERSION:+==$TARGET_VERSION}"
pip install ${WHEELS_DIRECTORY:+--find-links="$WHEELS_DIRECTORY"} --prefer-binary "$ASSISTANT_SOURCE" "$BINDINGS_SOURCE"
