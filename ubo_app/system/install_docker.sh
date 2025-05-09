#!/usr/bin/env bash

set -o xtrace
set -o errexit
set -o pipefail
set -o nounset

UPDATE_PREPARATION=${UPDATE_PREPARATION:-false}
OFFLINE=${OFFLINE:-false}

export DEBIAN_FRONTEND=noninteractive

for arg in "$@"; do
  case $arg in
  --update-preparation)
    UPDATE_PREPARATION=true
    shift
    ;;
  --offline)
    OFFLINE=true
    shift
    ;;
  *)
    echo "Unknown option: $arg"
    exit 1
    ;;
  esac
done

# Check for root privileges
if [ "$(id -u)" != "0" ]; then
  echo "This script must be run as root" 1>&2
  exit 1
fi

# Source: https://docs.docker.com/engine/install/debian/#install-using-the-repository
# Add Docker's official GPG key:

if [ "$OFFLINE" = false ]; then
  apt-get -y install \
    ca-certificates curl gnupg \
    --no-install-recommends --no-install-suggests
  install -m 0755 -d /etc/apt/keyrings
  rm -f /etc/apt/keyrings/docker.gpg
  curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg

  # Add the repository to Apt sources:
  echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" |
    tee /etc/apt/sources.list.d/docker.list >/dev/null

  apt-get -y install \
    docker-ce \
    docker-ce-cli \
    containerd.io \
    docker-buildx-plugin \
    docker-compose-plugin \
    --no-install-recommends --no-install-suggests
  apt-get -y clean
fi

if [ "$UPDATE_PREPARATION" = true ]; then
  echo "Assets downloaded, please run the script again without --update-preparation"
  exit 0
fi

usermod -aG docker $USERNAME
