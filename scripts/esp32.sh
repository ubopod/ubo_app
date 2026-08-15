#!/usr/bin/env bash
# Build / flash / monitor the ESP32 LVGL firmware for either supported board.
#
# Usage (via poe):
#   uv run poe esp32:build   --board c6
#   uv run poe esp32:flash   --board s3 --port /dev/cu.usbmodem101
#   uv run poe esp32:monitor --board s3
#
# Each (board, profile) pair gets its own build dir and sdkconfig — `set-target`
# wipes whatever is in the build dir, so sharing one would make the two boards
# clobber each other. The per-profile sdkconfig name also sidesteps the
# `sdkconfig.defaults*`-is-only-read-when-sdkconfig-is-absent trap: a given
# sdkconfig file is only ever generated from one defaults list. Pass --fresh to
# regenerate it after editing a checked-in sdkconfig.defaults* file.
set -o errexit
set -o nounset
set -o pipefail

action=${1:?usage: esp32.sh <build|flash|monitor> (invoke via uv run poe esp32:<action>)}

# poe exposes named task args as environment variables.
board=${board:-}
profile=${profile:-ppp}
port=${port:-}
transport=${transport:-}
fresh=${fresh:-False}

case "$board" in
c6 | esp32c6) target=esp32c6 ;;
s3 | esp32s3) target=esp32s3 ;;
*)
  echo "--board is required: c6 (Waveshare ESP32-C6-Touch-AMOLED-1.8) or s3 (Espressif ESP32-S3-BOX-3)" >&2
  exit 1
  ;;
esac

case "$profile" in
# The shipping build: gRPC traffic to ubo-core over the USB cable as a PPP
# link. No USB serial console — `esp32:monitor` shows nothing on this profile.
ppp)
  suffix=.ppp
  defaults="sdkconfig.defaults;sdkconfig.defaults.ppp"
  ;;
# Debug build: WiFi transport, USB console intact.
wifi)
  suffix=""
  defaults="sdkconfig.defaults"
  ;;
*)
  echo "--profile must be ppp (shipping, USB/PPP link) or wifi (debug, USB console)" >&2
  exit 1
  ;;
esac

cd "$(dirname "$0")/../ubo_lvgl/esp32"

build_dir="build.$target$suffix"
sdkconfig="sdkconfig.$target$suffix"

if [ "$fresh" = "True" ]; then
  echo "==> removing $build_dir and $sdkconfig"
  rm -rf "$build_dir" "$sdkconfig"
fi

# ESP-IDF is installed via EIM, whose layout `$IDF_PATH/export.sh` cannot
# activate (idf_tools.py reports every toolchain as uninstalled), and whose own
# activation script refuses to be sourced from a script — its is_sourced() test
# only recognizes $0 values like `bash`/`zsh`, so from here it would `exit 1`
# and take this shell with it. It does have a `-e` mode that prints the
# environment instead of applying it, which is what we use; the paths it does
# not print (IDF_PATH, the Python venv) come from EIM's own index.
# An IDF_PATH already in the environment wins over all of this.
if [ -z "${IDF_PATH:-}" ]; then
  eim_index="${IDF_TOOLS_PATH:-$HOME/.espressif/tools}/eim_idf.json"
  if [ ! -f "$eim_index" ]; then
    echo "no ESP-IDF install found ($eim_index missing); export IDF_PATH yourself or install ESP-IDF v6.0.1 via EIM" >&2
    exit 1
  fi
  eval "$(
    python3 - "$eim_index" <<'PY'
import json
import shlex
import sys

index = json.load(open(sys.argv[1]))
installs = index['idfInstalled']
selected = index.get('idfSelectedId')
install = next((i for i in installs if i['id'] == selected), installs[0])
print(f'IDF_PATH={shlex.quote(install["path"])}')
print(f'IDF_TOOLS_PATH={shlex.quote(install["idfToolsPath"])}')
print(f'idf_python={shlex.quote(install["python"])}')
print(f'idf_activate={shlex.quote(install["activationScript"])}')
print(f'ESP_IDF_VERSION={shlex.quote(install["name"].lstrip("v"))}')
PY
  )"
  # The cross toolchains and ninja. `-e` also prints SYSTEM_PATH (a snapshot of
  # the login PATH taken at install time) — dropped, since the live PATH is
  # what carries the rest of the build's tools, cmake included.
  idf_tools_path_entries=$(sh "$idf_activate" -e | sed -n 's/^PATH=//p')
  PATH="$idf_tools_path_entries:$PATH"
  IDF_PYTHON_ENV_PATH=$(dirname "$(dirname "$idf_python")")
  # EIM can hold two copies of the same version and index one while its
  # activation script points at the other. CMake bakes the IDF_PATH it was
  # configured with into the bootloader subproject cache and hard-errors on a
  # mismatch, so follow the activation script — that is the tree every
  # interactive `idf.py` on this machine uses — and keep the index as fallback.
  idf_activate_path=$(sed -n 's|.*"\(/.*/esp-idf\)/tools/idf\.py".*|\1|p' "$idf_activate" | head -1)
  if [ -n "$idf_activate_path" ] && [ -f "$idf_activate_path/tools/idf.py" ]; then
    IDF_PATH=$idf_activate_path
  fi
  export PATH IDF_PATH IDF_TOOLS_PATH IDF_PYTHON_ENV_PATH ESP_IDF_VERSION
fi

idf() { "${IDF_PYTHON_ENV_PATH:?}/bin/python" "$IDF_PATH/tools/idf.py" "$@"; }

args=(-B "$build_dir" -D SDKCONFIG="$sdkconfig" -D SDKCONFIG_DEFAULTS="$defaults")
if [ -n "$transport" ]; then
  args+=(-D UBO_TRANSPORT="$transport")
fi
if [ -n "$port" ]; then
  args+=(-p "$port")
fi

# CONFIG_IDF_TARGET is deliberately not pinned in sdkconfig.defaults, so the
# chip has to be selected explicitly the first time round. Gate that on the
# sdkconfig rather than the build dir: set-target renames an existing sdkconfig
# to .old and regenerates it from the defaults, which would silently discard
# menuconfig'd settings (WiFi credentials, core endpoint) every time the build
# dir went missing. With the sdkconfig present, its CONFIG_IDF_TARGET is enough
# to reconfigure an empty build dir.
if [ ! -f "$sdkconfig" ]; then
  echo "==> set-target $target ($build_dir)"
  idf "${args[@]}" set-target "$target"
fi

echo "==> $action $target/$profile ($build_dir)"
idf "${args[@]}" "$action"
