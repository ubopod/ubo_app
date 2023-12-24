#!/usr/bin/env sh

set -e -o errexit

poetry build

LATEST_VERSION=$(basename $(ls -rt dist/*.whl | tail -n 1))

scp dist/$LATEST_VERSION pi@ubo-development-pod:/tmp/
test "$deps" == "True" && ssh pi@ubo-development-pod "source ubo-app/bin/activate; pip install --upgrade /tmp/$LATEST_VERSION[dev]"
ssh pi@ubo-development-pod "source \$HOME/.profile && source /etc/profile && source ubo-app/bin/activate && pip install --upgrade --force-reinstal --no-deps /tmp/$LATEST_VERSION[dev]"
test "$run" == "True" && ssh pi@ubo-development-pod "source ubo-app/bin/activate; sudo killall ubo -9; sudo \$(which ubo)"
