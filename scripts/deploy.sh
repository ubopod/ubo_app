#!/usr/bin/env sh

set -o errexit
set -o pipefail
set -o nounset

perl -i -pe 's/^(packages = \[.*)$/\1\nexclude = ["ubo_app\/services\/*-voice\/models\/*"]/' pyproject.toml
poetry build
perl -i -pe 's/^exclude = .*-voice\/models.*\n//' pyproject.toml

LATEST_VERSION=$(basename $(ls -rt dist/*.whl | tail -n 1))
deps=${deps:-"False"}
bootstrap=${bootstrap:-"False"}
run=${run:-"False"}
restart=${restart:-"False"}
env=${env:-"False"}

function run_on_pod() {
  if [ $# -lt 1 ]; then
    echo "Usage: run_on_pod <command>"
    return 1
  fi
  if [ $# -eq 1 ]; then
    ssh ubo-development-pod "sudo XDG_RUNTIME_DIR=/run/user/\$(id -u ubo) -u ubo bash -c 'source \$HOME/.profile && source /etc/profile && source /opt/ubo/env/bin/activate && $1'"
    return 0
  fi
  return 1
}

function run_on_pod_as_root() {
  if [ $# -lt 1 ] || [ $# -gt 2 ]; then
    echo "Usage: run_on_pod_as_root <command>"
    return 1
  fi
  if [ $# -eq 1 ]; then
    ssh ubo-development-pod "sudo bash -c '$1'"
    return 0
  fi
  return 1
}

scp dist/$LATEST_VERSION ubo-development-pod:/tmp/

test "$deps" == "True" && run_on_pod "pip install --upgrade /tmp/$LATEST_VERSION[default]"

run_on_pod "mv /opt/ubo/env/lib/python3.*/site-packages/ubo_app/services/*-voice/models /tmp/
pip install --no-index --upgrade --force-reinstal --no-deps /tmp/$LATEST_VERSION[default]
mv /tmp/models /opt/ubo/env/lib/python3.*/site-packages/ubo_app/services/*-voice/"

test "$bootstrap" == "True" &&
  run_on_pod_as_root "/opt/ubo/env/bin/bootstrap; systemctl restart ubo-system.service"

test "$env" == "True" &&
  scp ubo_app/.dev.env ubo-development-pod:/tmp/ &&
  run_on_pod_as_root "chown ubo:ubo /tmp/.dev.env" &&
  run_on_pod "mv /tmp/.dev.env /opt/ubo/env/lib/python3.11/site-packages/ubo_app/"

test "$run" == "True" &&
  run_on_pod "systemctl --user restart ubo-app.service"

test "$restart" == "True" &&
  run_on_pod "killall -9 ubo"
