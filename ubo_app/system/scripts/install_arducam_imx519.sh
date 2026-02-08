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

if [ ! -f /etc/rpi-issue ]; then
  echo "Sorry, this driver only works on Raspberry Pi"
  exit 1
fi

# Accept variant argument: "autofocus" or "fixed-focus"
VARIANT="${1:-autofocus}"

WORKDIR=$(mktemp -d)
cd "$WORKDIR"

# Download Arducam install helper script
wget -O install_pivariety_pkgs.sh https://github.com/ArduCAM/Arducam-Pivariety-V4L2-Driver/releases/download/install_script/install_pivariety_pkgs.sh
chmod +x install_pivariety_pkgs.sh

# Install libcamera dev and apps
./install_pivariety_pkgs.sh -p libcamera_dev
./install_pivariety_pkgs.sh -p libcamera_apps

# Configure dtoverlay in /boot/firmware/config.txt
CONFIG="/boot/firmware/config.txt"

# Set camera_auto_detect=0
if grep -q "^camera_auto_detect=" "$CONFIG"; then
  sed -i 's/^camera_auto_detect=.*/camera_auto_detect=0/' "$CONFIG"
else
  echo "camera_auto_detect=0" >>"$CONFIG"
fi

# Remove any existing imx519 dtoverlay lines
sed -i '/^dtoverlay=imx519/d' "$CONFIG"

# Add the appropriate dtoverlay under [all] section
if [ "$VARIANT" = "fixed-focus" ]; then
  OVERLAY="dtoverlay=imx519,vcm=off"
else
  OVERLAY="dtoverlay=imx519"
fi

# Add under [all] section if it exists, otherwise append
if grep -q "^\[all\]" "$CONFIG"; then
  sed -i "/^\[all\]/a $OVERLAY" "$CONFIG"
else
  printf '\n[all]\n%s\n' "$OVERLAY" >>"$CONFIG"
fi

# Cleanup
cd /
rm -rf "$WORKDIR"

echo "------------------------------------------------------"
echo "Arducam IMX519 ($VARIANT) driver installed successfully"
echo "Please reboot your Raspberry Pi to apply all settings"
echo "------------------------------------------------------"
