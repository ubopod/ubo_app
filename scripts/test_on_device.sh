#!/usr/bin/env sh

set -o errexit
set -o pipefail
set -o nounset

# Signal handler
function cleanup() {
  run_on_pod "killall -9 pytest"
}
trap cleanup ERR
trap cleanup EXIT

copy=${copy:-"False"}
deps=${deps:-"False"}
run=${run:-"False"}

function run_on_pod() {
  echo $1
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


if [ "$copy" == "True" ]; then
  # Since rsync is not called with -r, it treats ./scripts as an empty directory and its content are ignored, it could be any other random directory inside "./". It is needed solely to create the root directory with ubo:ubo ownership.
  (echo './scripts'; git ls-files --others --exclude-standard --cached) | rsync --rsync-path="sudo rsync" --delete --info=progress2 -ae ssh --files-from=- --ignore-missing-args ./ ubo-development-pod:/home/ubo/test-runner/ --chown ubo:ubo
fi

run_on_pod "$(if [ "$copy" == "True" ]; then echo "(~/.local/bin/poetry --version || \
  curl -L https://install.python-poetry.org | python3 -) &&"; fi)
  $(if [ "$run" == "True" ]; then echo "(killall -9 pytest || true) &&"; fi)\
  cd ~/test-runner &&\
  $(if [ "$run" == "True" ] || [ "$deps" == "True" ]; then echo "~/.local/bin/poetry config virtualenvs.options.system-site-packages true --local &&\
  ~/.local/bin/poetry env use python3.11 &&"; fi)\
  $(if [ "$deps" == "True" ]; then echo "~/.local/bin/poetry install --no-interaction --extras=dev --with=dev &&"; fi)\
  $(if [ "$run" == "True" ]; then echo "~/.local/bin/poetry run poe test --verbosity=2 --capture=no --make-screenshots -n1 $* || true &&"; fi)\
  true"

if [ "$run" == "True" ]; then
  rm -rf tests/**/results/
  run_on_pod "find ~/test-runner -printf %P\\\\n | grep '^tests/.*/results$'" | rsync --rsync-path="sudo rsync" --info=progress2 --delete -are ssh --files-from=- --ignore-missing-args ubo-development-pod:/home/ubo/test-runner ./
fi
