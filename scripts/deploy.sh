#!/usr/bin/env sh

set -o errexit
set -o pipefail
set -o nounset

# Signal handler
function cleanup() {
  perl -i -pe 's/^exclude = .*-voice\/models.*\n//' pyproject.toml
}
trap cleanup ERR
trap cleanup EXIT

deps=${deps:-"False"}
bootstrap=${bootstrap:-"False"}
kill=${kill:-"False"}
restart=${restart:-"False"}
env=${env:-"False"}

perl -i -pe 's/^(packages = \[.*)$/\1\nexclude = ["ubo_app\/services\/*-voice\/models\/*"]/' pyproject.toml
uv build
cleanup
LATEST_VERSION=$(basename $(ls -rt dist/*.whl | tail -n 1))

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

run_on_pod "$(if [ "$deps" == "True" ]; then echo "pip install --upgrade /tmp/$LATEST_VERSION[default] &&"; fi)
mv /opt/ubo/env/lib/python3.*/site-packages/ubo_app/services/*-voice/models /tmp/
pip install --no-index --upgrade --force-reinstal --no-deps /tmp/$LATEST_VERSION[default]
mv /tmp/models /opt/ubo/env/lib/python3.*/site-packages/ubo_app/services/*-voice/
true"

if [ "$bootstrap" == "True" ] || [ "$env" == "True" ] || [ "$restart" == "True" ]; then
  run_on_pod_as_root "$(if [ "$bootstrap" == "True" ]; then echo "/opt/ubo/env/bin/bootstrap && systemctl daemon-reload && systemctl restart ubo-system.service &&"; fi)
$(if [ "$env" == "True" ]; then echo "cat <<'EOF' > /tmp/.dev.env
$(cat ubo_app/.dev.env)
EOF &&
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
