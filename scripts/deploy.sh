#!/usr/bin/env sh

set -o errexit
set -o pipefail
set -o nounset

poetry build

LATEST_VERSION=$(basename $(ls -rt dist/*.whl | tail -n 1))
deps=${deps:-"False"}
bootstrap=${bootstrap:-"False"}
run=${run:-"False"}

function run_on_pod() {
  if [ $# -lt 1 ] || [ $# -gt 2 ]; then
    echo "Usage: run_on_pod <command> [is_root]"
    exit 1
  fi
  if [ $# -eq 1 ]; then
    ssh ubo-development-pod "sudo XDG_RUNTIME_DIR=/run/user/\$(id -u ubo) -u ubo bash -c 'source \$HOME/.profile && source /etc/profile && source /opt/ubo/env/bin/activate && $1'"
    exit 0
  fi
  if [ "$2" == "root" ]; then
    ssh ubo-development-pod "sudo bash -c '$1'"
    exit 0
  fi
}

scp dist/$LATEST_VERSION ubo-development-pod:/tmp/

test "$deps" == "True" && run_on_pod "pip install --upgrade /tmp/$LATEST_VERSION[default]"

run_on_pod "pip install --upgrade --force-reinstal --no-deps /tmp/$LATEST_VERSION[default]"

test "$bootstrap" == "True" &&
  run_on_pod "/opt/ubo/env/bin/bootstrap; systemctl restart ubo-system.service" "root"

test "$run" == "True" &&
  run_on_pod "systemctl --user restart ubo-app.service"

test "$env" == "True" &&
  scp ubo_app/.dev.env /opt/ubo/env/lib/python3.11/site-packages/ubo_app/.env
