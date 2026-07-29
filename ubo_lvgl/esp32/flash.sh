#!/usr/bin/env bash
# Flash the ESP32 display client while it is cabled to a Pi that runs the PPP
# link over the very same port.
#
# pppd holds /dev/ubo-esp32 open, and esptool re-enumerates the port mid-flash —
# which retriggers the udev rule and would restart pppd straight into the
# flashing session. So the unit is masked (--runtime, i.e. until reboot: we do
# not want to leave a persistent mask behind if this script dies) and stopped
# for the duration, then unmasked.
#
# Usage:  sudo ./flash.sh [<merged.bin>]
# Default binary: build/ubo-lvgl-$UBO_ESP32_CHIP-merged.bin, or pass a release
# image. Override the chip with UBO_ESP32_CHIP=esp32s3 (default esp32c6).
#
# This script is specifically for a board cabled to a Pi over the PPP link. For
# a board on a normal USB port — including the ESP32-S3-BOX-3, which has no PPP
# profile — just use `idf.py -p <port> flash`.
set -euo pipefail

UNIT=ubo-esp32-ppp
PORT=${UBO_ESP32_PORT:-/dev/ubo-esp32}
CHIP=${UBO_ESP32_CHIP:-esp32c6}
BIN=${1:-build/ubo-lvgl-$CHIP-merged.bin}

if [[ ! -e $BIN ]]; then
  echo "no such image: $BIN" >&2
  exit 1
fi
if [[ ! -e $PORT ]]; then
  echo "no such port: $PORT (is the board plugged in? is the udev rule installed?)" >&2
  exit 1
fi

cleanup() {
  systemctl unmask --runtime "$UNIT" 2>/dev/null || true
  # The board re-enumerates after a flash; let udev re-fire SYSTEMD_WANTS rather
  # than starting the unit by hand, so a board that failed to come back doesn't
  # leave pppd spinning on a missing device.
  udevadm trigger --subsystem-match=tty || true
}
trap cleanup EXIT

echo "==> masking + stopping $UNIT"
systemctl mask --runtime "$UNIT"
systemctl stop "$UNIT" || true

echo "==> flashing $BIN to $PORT"
esptool --chip "$CHIP" --port "$PORT" --before default-reset --after hard-reset \
  write-flash 0x0 "$BIN"

echo "==> done; $UNIT will be restarted by udev on re-enumeration"
