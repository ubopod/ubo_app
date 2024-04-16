#!/usr/bin/env bash

set -o xtrace
set -o errexit
set -o pipefail
set -o nounset

git clone https://github.com/waveshare/WM8960-Audio-HAT
cd WM8960-Audio-HAT

./install.sh

cd ..
rm -rf WM8960-Audio-HAT
