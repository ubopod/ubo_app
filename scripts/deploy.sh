#!/usr/bin/env sh

set -o errexit
set -o pipefail
set -o nounset
shopt -s nullglob

skip_deps=${skip_deps:-"False"}
bootstrap=${bootstrap:-"False"}
kill=${kill:-"False"}
restart=${restart:-"False"}
env=${env:-"True"}
offline=${offline:-"False"}

echo "Building ubo-app"
if [ "$offline" == "True" ]; then
  uv --offline build
else
  uv build
fi

echo "Building rpc bindings"
if [ "$offline" == "True" ]; then
  uv --offline build --directory ubo_app/rpc
else
  uv build --directory ubo_app/rpc
fi

LATEST_UBO_APP_WHEEL=$(basename $(ls -rt dist/ubo_app-*.whl | tail -n 1))
LATEST_BINDINGS_WHEEL=$(basename $(ls -rt dist/ubo_app_raw_bindings-*.whl | tail -n 1))

function run_on_pod() {
  if [ $# -lt 1 ]; then
    echo "Usage: run_on_pod <command>"
    return 1
  fi
  if [ $# -eq 1 ]; then
    ssh ubo-development-pod-$index "sudo XDG_RUNTIME_DIR=/run/user/\$(id -u ubo) -u ubo bash -c 'source \$HOME/.profile && source /etc/profile && source /opt/ubo/env/bin/activate && $1'"
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

run_on_pod_as_root "rm /tmp/ubo*.whl || true"
scp dist/$LATEST_UBO_APP_WHEEL ubo-development-pod-$index:/tmp/
scp dist/$LATEST_BINDINGS_WHEEL ubo-development-pod-$index:/tmp/

# Sweep orphaned `~`-prefixed service dirs left by a prior interrupted in-place
# `--force-reinstall` (e.g. `090-web-ui` -> `~90-web-ui`). They sort after the
# canonical `0NN-*` dirs and would otherwise shadow them at load time. The
# loader also skips them defensively (see is_loadable_service_dir), but cleaning
# them here keeps the install tree tidy.
run_on_pod "rm -rf /opt/ubo/env/lib/python*/site-packages/ubo_app/services/~* 2>/dev/null || true
$(if [ "$skip_deps" != "True" ]; then echo "pip install --upgrade /tmp/$LATEST_UBO_APP_WHEEL &&"; fi)
pip install --no-index --upgrade --force-reinstall --no-deps /tmp/$LATEST_UBO_APP_WHEEL &&
pip install --no-index --upgrade --force-reinstall --no-deps /tmp/$LATEST_BINDINGS_WHEEL
true"

if [ "$bootstrap" == "True" ] || [ "$env" == "True" ] || [ "$restart" == "True" ]; then
  run_on_pod_as_root "$(if [ "$bootstrap" == "True" ]; then echo "/opt/ubo/env/bin/ubo-bootstrap && systemctl daemon-reload && systemctl restart ubo-system.service &&"; fi)
$(if [ "$env" == "True" ]; then echo "cat <<EOF > /tmp/.dev.env
$(cat ubo_app/.pod.dev.env)
EOF
chown ubo:ubo /tmp/.dev.env &&
mv /tmp/.dev.env /opt/ubo/env/lib/python3.*/site-packages/ubo_app/ &&"; fi)
$(if [ "$restart" == "True" ]; then echo "systemctl restart ubo-system.service &&"; fi)
true"
fi

for service in ubo_app/services/*/ubo-service; do
  args=(--index="$index")
  [[ "$skip_deps" == "True" ]] && args+=("--skip_deps")
  [[ "$offline" == "True" ]] && args+=("--offline")
  uv run --directory "$service" poe deploy-to-device "${args[@]}"
done

# Build and deploy GUI client
gui_args=(--index="$index")
[[ "$skip_deps" != "True" ]] && gui_args+=("--deps")
[[ "$offline" == "True" ]] && gui_args+=("--offline")
uv run --directory ubo_app/gui poe deploy-to-device "${gui_args[@]}"

# Restart the app last, after every wheel (core, services, gui-client) is installed,
# so the running processes load the freshly deployed code.
if [ "$kill" == "True" ] || [ "$restart" == "True" ]; then
  run_on_pod "$(if [ "$kill" == "True" ]; then echo "(killall -9 ubo || true) &&"; fi)
$(if [ "$restart" == "True" ]; then echo "systemctl --user restart ubo-app.service &&"; fi)
true"
fi
