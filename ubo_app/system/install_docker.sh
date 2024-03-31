#!/usr/bin/env bash

set -o xtrace
set -o errexit
set -o pipefail
set -o nounset

# Source: https://docs.docker.com/engine/install/debian/#install-using-the-repository
# Add Docker's official GPG key:

apt-get -y install \
  ca-certificates curl gnupg \
  --no-install-recommends --no-install-suggests
sudo install -m 0755 -d /etc/apt/keyrings
rm -f /etc/apt/keyrings/docker.gpg
curl -fsSL https://download.docker.com/linux/debian/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Add the repository to Apt sources:
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

apt-get -y update

apt-get -y install \
  docker-ce \
  docker-ce-cli \
  containerd.io \
  docker-buildx-plugin \
  docker-compose-plugin \
  --no-install-recommends --no-install-suggests

usermod -aG docker $USERNAME
