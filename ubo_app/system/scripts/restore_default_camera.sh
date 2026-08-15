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

# `sed -i` writes a temporary file into the target's directory and renames it,
# so an unwritable /boot/firmware fails the edit even as root. That happens when
# the boot partition is mounted read-only — either deliberately or because the
# kernel remounted the vfat filesystem after an error. Recover by remounting
# read-write, and fail with the real reason rather than a bare sed error.
boot_config_writable() {
  # sed -i needs to create a temp file in the directory and rename over the
  # target, so probe the directory too — not just the file.
  local probe="$(dirname "$CONFIG")/.ubo-write-probe.$$"
  if [ -w "$CONFIG" ] && (: >"$probe") 2>/dev/null; then
    rm -f "$probe"
    return 0
  fi
  rm -f "$probe" 2>/dev/null || true
  return 1
}

ensure_boot_config_writable() {
  if [ ! -f "$CONFIG" ]; then
    echo "ERROR: $CONFIG not found; is this a Raspberry Pi OS boot partition?" 1>&2
    exit 1
  fi

  if boot_config_writable; then
    return 0
  fi

  echo "$CONFIG is not writable, attempting to remount read-write..." 1>&2
  mount -o remount,rw /boot/firmware || true

  if boot_config_writable; then
    echo "Remounted /boot/firmware read-write."
    return 0
  fi

  echo "ERROR: cannot write $CONFIG." 1>&2
  echo "Mount state:" 1>&2
  findmnt -no SOURCE,FSTYPE,OPTIONS /boot/firmware 1>&2 || true
  exit 1
}

ensure_boot_config_writable

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
