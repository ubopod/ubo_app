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

# Install Node.js (and the bundled npx) via fnm under the ubo user so stdio MCP
# servers launched by the gateway can run `npx <server>`.
if [ -x "$LOCAL_BIN/npx" ]; then
  echo "node already installed at $LOCAL_BIN/npx, skipping."
  exit 0
fi

echo "Installing node (via fnm) for user $USERNAME..."
sudo -u "$USERNAME" HOME="/home/$USERNAME" bash -c '
  set -e
  LOCAL_BIN="$HOME/.local/bin"
  mkdir -p "$LOCAL_BIN"
  command -v "$LOCAL_BIN/fnm" >/dev/null 2>&1 || \
    curl -fsSL https://fnm.vercel.app/install | bash -s -- --install-dir "$LOCAL_BIN" --skip-shell
  export PATH="$LOCAL_BIN:$PATH"
  eval "$(fnm env)"
  fnm install --lts
  fnm use lts-latest
  fnm default lts-latest
  # Stable symlinks so node/npm/npx live in one dir (~/.local/bin), independent
  # of the version-specific install directory fnm manages.
  NODE_BIN="$(dirname "$(which node)")"
  ln -sf "$NODE_BIN/node" "$LOCAL_BIN/node"
  ln -sf "$NODE_BIN/npm"  "$LOCAL_BIN/npm"
  ln -sf "$NODE_BIN/npx"  "$LOCAL_BIN/npx"
'
echo "node installed successfully at $LOCAL_BIN/npx."
