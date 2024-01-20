#!/usr/bin/env sh

set -e -o errexit

poetry build

LATEST_VERSION=$(basename $(ls -rt dist/*.whl | tail -n 1))

scp dist/$LATEST_VERSION pi@ubo-development-pod:/tmp/
test "$deps" == "True" && ssh pi@ubo-development-pod "sudo -u ubo bash -c 'source /opt/ubo/env/bin/activate; pip install --upgrade /tmp/$LATEST_VERSION[default]'"
ssh pi@ubo-development-pod "sudo -u ubo bash -c 'source \$HOME/.profile && source /etc/profile && source /opt/ubo/env/bin/activate && pip install --upgrade --force-reinstal --no-deps /tmp/$LATEST_VERSION[default]'"
test "$run" == "True" && ssh pi@ubo-development-pod "sudo service ubo-app restart"
