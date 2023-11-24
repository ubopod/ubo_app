#!/usr/bin/env sh

set -e -o errexit

poetry build

LATEST_VERSION=$(basename $(ls -rt dist/*.whl | tail -n 1))

scp dist/$LATEST_VERSION pi@ubo-development-pod:/tmp/
ssh pi@ubo-development-pod "source ubo-app/bin/activate && pip install --upgrade --force-reinstall --no-deps /tmp/$LATEST_VERSION && (killall ubo -9 || true) && ubo"
