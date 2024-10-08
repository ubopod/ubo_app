#!/usr/bin/env sh

set -o errexit
set -o pipefail
set -o nounset

# Signal handler
function cleanup() {
  run_on_pod killall -9 pytest
}
trap cleanup ERR
trap cleanup SIGINT

copy=${copy:-"False"}
deps=${deps:-"False"}
run=${run:-"False"}
results=${results:-"False"}

function run_on_pod() {
  if [ $# -lt 1 ]; then
    echo "Usage: run_on_pod <command>"
    return 1
  fi

  # Use SSH to execute commands read from stdin
  ssh ubo-development-pod "sudo XDG_RUNTIME_DIR=/run/user/\$(id -u ubo) -u ubo bash -s" <<EOF
cd
source /etc/profile
source "\$HOME/.profile"
$*
EOF
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
  (echo ./scripts; echo ./ubo_app/_version.py; git ls-files --others --exclude-standard --cached) | rsync --rsync-path="sudo rsync" --delete --info=progress2 -ae ssh --files-from=- --ignore-missing-args ./ ubo-development-pod:/home/ubo/test-runner/ --chown ubo:ubo
fi

if [ "$run" == "True" ] || [ "$deps" == "True" ] || [ "$copy" == "True" ]; then
  # Initialize an array to build the command
  cmd_list=()

  # Conditional commands based on the flags
  if [ "$deps" == "True" ]; then
    cmd_list+=("(uv --version || curl -LsSf https://astral.sh/uv/install.sh | sh) &&")
  fi

  if [ "$copy" == "True" ]; then
    cmd_list+=('perl -pi -e "s|source = \"vcs\"|path = \"ubo_app/_version.py\"\\npattern = \"version = '\''\(?P<version>[^'\'']+\)'\''\"|" ~/test-runner/pyproject.toml && cd ~/test-runner && uv python pin python3.11 && uv venv --system-site-packages && true')
  fi

  if [ "$run" == "True" ]; then
    cmd_list+=("killall -9 pytest || true && systemctl --user stop ubo-app || true &&")
  fi

  # Common commands
  cmd_list+=("cd ~/test-runner &&")
  cmd_list+=("uv venv --system-site-packages &&")
  cmd_list+=("uv python pin python3.11 &&")

  if [ "$deps" == "True" ]; then
    cmd_list+=('SETUPTOOLS_SCM_PRETEND_VERSION=$(uvx hatch version) uv sync --frozen &&')
  fi

  if [ "$run" == "True" ]; then
    cmd_list+=("uv run poe test --verbosity=2 --capture=no --make-screenshots -n1 $* || true &&")
  fi

  # Add a final true to ensure the command exits successfully
  cmd_list+=("true")

  # Combine the commands into a single string
  cmd="${cmd_list[*]}"

  # Execute the command on the pod
  run_on_pod $cmd
fi

if [ "$run" == "True" ] || [ "$results" == True ]; then
  rm -rf tests/**/results/
  run_on_pod "find ~/test-runner -printf %P\\\\n | grep '^tests/.*/results$'" | rsync --rsync-path="sudo rsync" --info=progress2 --delete -are ssh --files-from=- --ignore-missing-args ubo-development-pod:/home/ubo/test-runner ./
fi
