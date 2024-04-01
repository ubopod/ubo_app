#!/usr/bin/env sh

set -o errexit
set -o pipefail
set -o nounset

poetry build

LATEST_VERSION=$(basename $(ls -rt dist/*.whl | tail -n 1))
deps=${deps:-"False"}
bootstrap=${bootstrap:-"False"}
run=${run:-"False"}

scp dist/$LATEST_VERSION pi@ubo-development-pod:/tmp/

test "$deps" == "True" && ssh pi@ubo-development-pod "sudo -u ubo bash -c 'source /opt/ubo/env/bin/activate; pip install --upgrade /tmp/$LATEST_VERSION[default]'"

ssh pi@ubo-development-pod "sudo -u ubo bash -c 'source \$HOME/.profile && source /etc/profile && source /opt/ubo/env/bin/activate && pip install --upgrade --force-reinstal --no-deps /tmp/$LATEST_VERSION[default]'"

test "$bootstrap" == "True" && ssh pi@ubo-development-pod "sudo /opt/ubo/env/bin/bootstrap; sudo systemctl restart ubo-system.service"
test "$run" == "True" && ssh pi@ubo-development-pod "sudo XDG_RUNTIME_DIR=/run/user/\$(id -u ubo) -u ubo systemctl --user restart ubo-app.service"
