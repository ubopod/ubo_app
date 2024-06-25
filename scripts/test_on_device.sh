#!/usr/bin/env sh

set -o errexit
set -o pipefail
set -o nounset

function run_on_pod() {
  if [ $# -lt 1 ]; then
    echo "Usage: run_on_pod_out_of_env <command>"
    return 1
  fi
  if [ $# -eq 1 ]; then
    ssh ubo-development-pod "sudo XDG_RUNTIME_DIR=/run/user/\$(id -u ubo) -u ubo bash -c 'cd; source \$HOME/.profile && source /etc/profile && ($1)'"
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

run_on_pod_as_root "rm -rf /tmp/test-runner"

git ls-files --others --exclude-standard --cached | rsync --info=progress2 -are ssh --files-from=- --ignore-missing-args ./ ubo-development-pod:/tmp/test-runner/

run_on_pod_as_root "chown -R ubo:ubo /tmp/test-runner"
run_on_pod "~/.local/bin/poetry --version || curl -L https://install.python-poetry.org | python3 -"
run_on_pod "killall -9 pytest || true"
run_on_pod "rm -rf ~/test-runner &&\
  mv /tmp/test-runner ~/ &&\
  cd ~/test-runner &&\
  ~/.local/bin/poetry config virtualenvs.options.system-site-packages true --local &&\
  ~/.local/bin/poetry env use python3.11 &&\
  ~/.local/bin/poetry install --no-interaction --extras=dev --with=dev &&\
  ~/.local/bin/poetry run poe test --make-screenshots -n1 $*; \
  mv ~/test-runner /tmp/"

rm -rf tests/**/results/
run_on_pod "find /tmp/test-runner -printf %P\\\\n | grep '^tests/.*/results$'" | rsync --info=progress2 --delete -are ssh --files-from=- --ignore-missing-args ubo-development-pod:/tmp/test-runner ./
