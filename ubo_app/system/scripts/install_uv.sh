#!/usr/bin/env bash

set -o xtrace
set -o errexit
set -o pipefail
set -o nounset

export DEBIAN_FRONTEND=noninteractive

# Check for root privileges
if [ "$(id -u)" != "0" ]; then
  echo "This script must be run as root" 1>&2
  exit 1
fi

USERNAME=${USERNAME:-"ubo"}
LOCAL_BIN="/home/$USERNAME/.local/bin"

# Install uv (and the bundled uvx) under the ubo user so stdio MCP servers
# launched by the gateway can run `uvx <server>`.
if [ -x "$LOCAL_BIN/uv" ]; then
  echo "uv already installed at $LOCAL_BIN/uv, skipping."
  exit 0
fi

echo "Installing uv for user $USERNAME..."
sudo -u "$USERNAME" HOME="/home/$USERNAME" sh -c \
  'curl -LsSf https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 INSTALLER_NO_MODIFY_PATH=1 sh'
echo "uv installed successfully at $LOCAL_BIN/uv."
