#!/usr/bin/env bash

set -o xtrace
set -o errexit
set -o pipefail
set -o nounset

# Check for root privileges
if [ "$(id -u)" != "0" ]; then
  echo "This script must be run as root" 1>&2
  exit 1
fi

CONFIG="/boot/firmware/config.txt"

# Remove any imx519 dtoverlay lines
sed -i '/^dtoverlay=imx519/d' "$CONFIG"

# Set camera_auto_detect=1
if grep -q "^camera_auto_detect=" "$CONFIG"; then
  sed -i 's/^camera_auto_detect=.*/camera_auto_detect=1/' "$CONFIG"
else
  echo "camera_auto_detect=1" >>"$CONFIG"
fi

echo "------------------------------------------------------"
echo "Default camera configuration restored successfully"
echo "Please reboot your Raspberry Pi to apply all settings"
echo "------------------------------------------------------"
