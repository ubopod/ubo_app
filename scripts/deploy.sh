#!/usr/bin/env sh

set -o errexit
set -o pipefail
set -o nounset

echo $0

deps=${deps:-"False"}
bootstrap=${bootstrap:-"False"}
kill=${kill:-"False"}
restart=${restart:-"False"}
env=${env:-"True"}
offline=${env:-"False"}

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

for service in $(ls -d ubo_app/services/*/ubo-service); do
  echo "Building service: $service"
  if [ "$offline" == "True" ]; then
    uv --offline build --directory "$service"
  else
    uv build --directory "$service"
  fi
done

LATEST_UBO_APP_WHEEL=$(basename $(ls -rt dist/*.whl | tail -n 1))
LATEST_BINDINGS_WHEEL=$(basename $(ls -rt ubo_app/rpc/dist/*.whl | tail -n 1))

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

scp dist/$LATEST_UBO_APP_WHEEL ubo-development-pod-$index:/tmp/
scp ubo_app/rpc/dist/$LATEST_BINDINGS_WHEEL ubo-development-pod-$index:/tmp/
for service in $(ls -d ubo_app/services/*/ubo-service); do
  SERVICE_WHEEL=$(basename $(ls -rt "$service"/dist/*.whl | tail -n 1))
  scp "$service"/dist/"$SERVICE_WHEEL" ubo-development-pod-$index:/tmp/
done

run_on_pod "$(if [ "$deps" == "True" ]; then echo "pip install --upgrade /tmp/$LATEST_UBO_APP_WHEEL &&"; fi)
pip install --no-index --upgrade --force-reinstal --no-deps /tmp/$LATEST_UBO_APP_WHEEL &&
pip install --no-index --upgrade --force-reinstal --no-deps /tmp/$LATEST_BINDINGS_WHEEL
true"

# Install service wheels
for service in $(ls -d ubo_app/services/*/ubo-service); do
  SERVICE_WHEEL=$(basename $(ls -rt "$service"/dist/*.whl | tail -n 1))
  run_on_pod "pip install --no-index --upgrade --force-reinstal --no-deps /tmp/$SERVICE_WHEEL"
done

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

if [ "$kill" == "True" ] || [ "$restart" == "True" ]; then
  run_on_pod "$(if [ "$kill" == "True" ]; then echo "killall -9 ubo &&"; fi)
$(if [ "$restart" == "True" ]; then echo "systemctl --user restart ubo-app.service &&"; fi)
true"
fi
