#!/usr/bin/env sh

set -o errexit
set -o pipefail
set -o nounset

skip_deps=${skip_deps:-"False"}
offline=${env:-"False"}

echo "Building ubo-assistant"
if [ "$offline" == "True" ]; then
  uv --offline build
else
  uv build
fi

echo "Building rpc bindings"
if [ "$offline" == "True" ]; then
  uv --offline build --directory ../../../rpc
else
  uv build --directory ../../../rpc
fi

LATEST_WHEEL=$(basename $(ls -rt dist/ubo_app_assistant-*.whl | tail -n 1))
LATEST_BINDINGS_WHEEL=$(basename $(ls -rt ../../../../dist/ubo_app_raw_bindings-*.whl | tail -n 1))

function run_on_pod() {
  if [ $# -lt 1 ]; then
    echo "Usage: run_on_pod <command>"
    return 1
  fi
  if [ $# -eq 1 ]; then
    ssh ubo-development-pod-$index "sudo XDG_RUNTIME_DIR=/run/user/\$(id -u ubo) -u ubo bash -c 'source \$HOME/.profile && source /etc/profile && source /opt/ubo/env/lib/python3.11/site-packages/ubo_app/services/090-assistant/ubo-service/bin/activate && $1'"
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
    ssh ubo-development-pod-$index "sudo bash -c '$1'"
    return 0
  fi
  return 1
}

run_on_pod_as_root "rm /tmp/ubo_app_assistant*.whl || true"
scp dist/$LATEST_WHEEL ubo-development-pod-$index:/tmp/
scp ../../../../dist/$LATEST_BINDINGS_WHEEL ubo-development-pod-$index:/tmp/

run_on_pod "$(if [ "$skip_deps" != "True" ]; then echo "pip install --upgrade /tmp/$LATEST_WHEEL &&"; fi)
pip install --no-index --upgrade --force-reinstall --no-deps /tmp/$LATEST_WHEEL
pip install --no-index --upgrade --force-reinstall --no-deps /tmp/$LATEST_BINDINGS_WHEEL
true"
