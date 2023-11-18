#!/usr/bin/env sh

set -e -o errexit

poetry build

LATEST_VERSION=$(basename $(ls -rt dist/*.whl | tail -n 1))

scp dist/$LATEST_VERSION pi@ubo-development-pod:/tmp/
ssh pi@ubo-development-pod "source ubo-gui/bin/activate && pip install --upgrade --force-reinstall --no-deps /tmp/$LATEST_VERSION && (killall demo-menu -9 || true) && demo-menu"
