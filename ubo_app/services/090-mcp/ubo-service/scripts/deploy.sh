#!/usr/bin/env sh

set -o errexit
set -o pipefail
set -o nounset

skip_deps=${skip_deps:-"False"}
offline=${env:-"False"}

echo "Building ubo-mcp-gateway"
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

LATEST_WHEEL=$(basename $(ls -rt dist/ubo_app_mcp_gateway-*.whl | tail -n 1))
LATEST_BINDINGS_WHEEL=$(basename $(ls -rt ../../../../dist/ubo_app_raw_bindings-*.whl | tail -n 1))

function run_on_pod() {
  if [ $# -lt 1 ]; then
    echo "Usage: run_on_pod <command>"
    return 1
  fi
  if [ $# -eq 1 ]; then
    ssh ubo-development-pod-$index "sudo XDG_RUNTIME_DIR=/run/user/\$(id -u ubo) -u ubo bash -c 'source \$HOME/.profile && source /etc/profile && source /opt/ubo/env/lib/python3.11/site-packages/ubo_app/services/090-mcp/ubo-service/bin/activate && $1'"
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

SERVICE_VENV="/opt/ubo/env/lib/python3.11/site-packages/ubo_app/services/090-mcp/ubo-service"

# The per-service venv is normally created at install time by
# `ubo-setup.sh`/`ubo-bootstrap`, which `pip install`s the service wheel from
# PyPI. A brand-new service whose wheel is not published yet never gets that
# venv, so `source .../bin/activate` below would fail. Create it on demand
# (mirrors bootstrap's `venv.create(system_site_packages=True)`) so a dev
# `deploy` provisions the service from scratch.
ssh ubo-development-pod-$index "sudo XDG_RUNTIME_DIR=/run/user/\$(id -u ubo) -u ubo bash -c 'source \$HOME/.profile && source /etc/profile && [ -f $SERVICE_VENV/bin/activate ] || /opt/ubo/env/bin/python -m venv --system-site-packages $SERVICE_VENV'"

run_on_pod_as_root "rm /tmp/ubo_app_mcp_gateway*.whl || true"
scp dist/$LATEST_WHEEL ubo-development-pod-$index:/tmp/
scp ../../../../dist/$LATEST_BINDINGS_WHEEL ubo-development-pod-$index:/tmp/

run_on_pod "$(if [ "$skip_deps" != "True" ]; then echo "pip install --upgrade /tmp/$LATEST_WHEEL &&"; fi)
pip install --no-index --upgrade --force-reinstall --no-deps /tmp/$LATEST_WHEEL
pip install --no-index --upgrade --force-reinstall --no-deps /tmp/$LATEST_BINDINGS_WHEEL
true"
