#!/usr/bin/env bash

set -o xtrace
set -o errexit
set -o pipefail
set -o nounset

git clone https://github.com/waveshare/WM8960-Audio-HAT
cd WM8960-Audio-HAT

IS_IN_PACKER=false

if [ $# -eq 1 ] && [ "$1" == "--in-packer" ]; then
  IS_IN_PACKER=true
fi

if [ "$IS_IN_PACKER" == "true" ]; then
  # Convincing the installer that we are on a Raspberry Pi as /proc/device-tree is not created in packer build
  sed -i 's/^is_Raspberry=.*/is_Raspberry="Raspberry"/' install.sh
fi

./install.sh

cd ..
rm -rf WM8960-Audio-HAT
