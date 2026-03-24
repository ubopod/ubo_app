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

deps="${deps:-False}"
copy="${copy:-False}"
run="${run:-False}"
results="${results:-False}"
index="${index:-1}"
pytest_args="${pytest_args:-}"

function run_on_pod() {
  if [ $# -lt 1 ]; then
    echo "Usage: run_on_pod <command>"
    return 1
  fi

  # Connect as pi user and run commands as ubo user
  ssh pi@ubo-development-pod-$index "sudo -u ubo bash -c 'XDG_RUNTIME_DIR=/run/user/\$(id -u ubo) bash -s'" <<EOF
cd /home/ubo
source /etc/profile
source /home/ubo/.profile 2>/dev/null || true
$*
EOF
}

function run_on_pod_as_root() {
  if [ $# -lt 1 ] || [ $# -gt 2 ]; then
    echo "Usage: run_on_pod_as_root <command>"
    return 1
  fi
  if [ $# -eq 1 ]; then
    ssh pi@ubo-development-pod-$index "sudo bash -c '$1'"
    return 0
  fi
  return 1
}

if [ "$copy" == "True" ]; then
  # Generate proto files locally before copying
  echo "Generating proto files locally..."
  uv run poe proto:generate:raw proto:compile:raw || echo "Proto generation failed, continuing anyway..."
  
  # Since rsync is not called with -r, it treats ./scripts as an empty directory and its content are ignored, it could be any other random directory inside "./". It is needed solely to create the root directory with ubo:ubo ownership.
  # Connect as pi user and use sudo rsync to copy files with ubo:ubo ownership
  (echo ./scripts; echo ./version.py; echo ./ubo_app/_version.py; echo ./ubo_app/rpc/ubo_bindings/__init__.py; find ./ubo_app/rpc/ubo_bindings/ubo -type f 2>/dev/null; find ./ubo_app/rpc/ubo_bindings/secrets -type f 2>/dev/null; find ./ubo_app/rpc/ubo_bindings/store -type f 2>/dev/null; find ./ubo_app/rpc/ubo_bindings/package_info -type f 2>/dev/null; git ls-files --others --exclude-standard --cached) | rsync --rsync-path="sudo rsync" --delete --info=progress2 -ae ssh --files-from=- --ignore-missing-args ./ pi@ubo-development-pod-$index:/home/ubo/test-runner/ --chown ubo:ubo
fi

if [ "$run" == "True" ] || [ "$deps" == "True" ] || [ "$copy" == "True" ]; then
  # Initialize an array to build the command
  cmd_list=()

  # Conditional commands based on the flags
  if [ "$deps" == "True" ]; then
    cmd_list+=("(uv --version || curl -LsSf https://astral.sh/uv/install.sh | sh) &&")
  fi

  if [ "$copy" == "True" ] || [ "$deps" == "True" ]; then
    cmd_list+=('sed -i "/\\[tool.hatch.version\\]/,/^$/c\\[tool.hatch.version]\\nsource = \"regex\"\\npath = \"ubo_app/_version.py\"\\npattern = \"version = .(?P<version>.+).\"" /home/ubo/test-runner/pyproject.toml && sed -i "/\\[tool.hatch.version\\]/,/^$/c\\[tool.hatch.version]\\nsource = \"regex\"\\npath = \"../_version.py\"\\npattern = \"version = .(?P<version>.+).\"" /home/ubo/test-runner/ubo_app/rpc/pyproject.toml && sed -i "/\\[tool.hatch.version\\]/,/^$/c\\[tool.hatch.version]\\nsource = \"regex\"\\npath = \"../../../_version.py\"\\npattern = \"version = .(?P<version>.+).\"" /home/ubo/test-runner/ubo_app/services/090-assistant/ubo-service/pyproject.toml && echo "DEBUG: POST-SED PYPROJECT:" && cat /home/ubo/test-runner/ubo_app/rpc/pyproject.toml && echo "Patched pyproject.toml files" && cd /home/ubo/test-runner && uv python pin python3.11 && uv venv --system-site-packages && true')
  fi

  if [ "$run" == "True" ]; then
    cmd_list+=("killall -9 pytest || true && systemctl --user stop ubo-app || true &&")
  fi

  # Common commands
  cmd_list+=("cd /home/ubo/test-runner &&")
  cmd_list+=("uv venv --system-site-packages &&")
  cmd_list+=("uv python pin python3.11 &&")

  if [ "$deps" == "True" ]; then
    cmd_list+=('SETUPTOOLS_SCM_PRETEND_VERSION=$(uv run poe version) uv run poe proto:generate:raw proto:compile:raw && uv sync --frozen && (cd ubo_app/gui && UV_PROJECT_ENVIRONMENT=.venv uv venv --system-site-packages .venv && UV_PROJECT_ENVIRONMENT=.venv uv sync --frozen) &&')
  fi

  if [ "$run" == "True" ]; then
    cmd_list+=("UBO_TEST_ENV=1 uv run --no-sync poe test -vv --tb=long -s -n1 $pytest_args 2>&1 || true &&")
  fi

  # Add a final true to ensure the command exits successfully
  cmd_list+=("true")

  # Combine the commands into a single string
  cmd="${cmd_list[*]}"

  # Execute the command on the pod
  run_on_pod $cmd
fi

if [ "$results" == "True" ]; then
  run_on_pod "find /home/ubo/test-runner -printf %P\\\\n | grep '^tests/.*/results$'" | rsync --rsync-path="sudo rsync" --info=progress2 --delete -are ssh --files-from=- --ignore-missing-args pi@ubo-development-pod-$index:/home/ubo/test-runner ./
fi
