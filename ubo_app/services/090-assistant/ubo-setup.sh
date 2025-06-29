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

pip install${WHEELS_DIRECTORY:+ --pre --find-links="$WHEELS_DIRECTORY"} --prefer-binary ubo-app-assistant
