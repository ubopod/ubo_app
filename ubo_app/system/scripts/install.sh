#!/usr/bin/env bash

set -o xtrace
set -o errexit
set -o pipefail
set -o nounset

if ! [ -f /etc/debian_version ]; then
  echo "This script only supports Debian-based systems."
  exit 1
fi

if ! python3 -c "import sys; exit(0) if sys.version_info >= (3, 11) else exit(1)"; then
  echo "Python 3.11 or higher is required"
  exit 1
fi

trap 'echo "Error on line $LINENO: $BASH_COMMAND" >&2' ERR

export DEBIAN_FRONTEND=noninteractive

# Parse arguments
for arg in "$@"; do
  case $arg in
  --username=*)
    USERNAME="${arg#*=}"
    shift
    ;;
  --target-version=*)
    TARGET_VERSION="${arg#*=}"
    shift
    ;;
  --installation-path=*)
    INSTALLATION_PATH="${arg#*=}"
    shift
    ;;
  --without-wm8960)
    WITHOUT_WM8960=true
    shift
    ;;
  --without-docker)
    WITHOUT_DOCKER=true
    shift
    ;;
  --wheels-directory=*)
    WHEELS_DIRECTORY="${arg#*=}"
    shift
    ;;
  --in-packer)
    IN_PACKER=true
    shift
    ;;
  *)
    echo "Unknown option: $arg"
    exit 1
    ;;
  esac
done

IS_RPI=""
if [ -f /etc/rpi-issue ]; then
  IS_RPI=true
fi

USERNAME=${USERNAME:-"ubo"}
TARGET_VERSION=${TARGET_VERSION:-}
INSTALLATION_PATH=${INSTALLATION_PATH:-"/opt/ubo"}
WITHOUT_WM8960=$([ "${WITHOUT_WM8960:-''}" = true ] && echo true || true)
WITHOUT_DOCKER=$([ "${WITHOUT_DOCKER:-''}" = true ] && echo true || true)
export WHEELS_DIRECTORY=${WHEELS_DIRECTORY:-""}
IN_PACKER=$([ "${IN_PACKER:-''}" = true ] && echo true || true)

if [ "$IS_RPI" != true ]; then
  echo "Running on non-Raspberry Pi system, disabling WM8960 driver installation."
  WITHOUT_WM8960=true
fi

# Check for root privileges
if [ "$(id -u)" != "0" ]; then
  echo "This script must be run as root" 1>&2
  exit 1
fi

if [ -z "$TARGET_VERSION" ]; then
  TARGET_VERSION=$(curl -s "https://pypi.org/pypi/ubo-app/json" | python3 -c "import sys, json; print(json.load(sys.stdin)['info']['version'])")
  if [ -z "$TARGET_VERSION" ]; then
    echo "Failed to retrieve the latest version from PyPI."
    exit 1
  fi
fi

echo "----------------------------------------------"
echo "Parameters:"
echo "USERNAME: \"$USERNAME\""
echo "TARGET_VERSION: \"$TARGET_VERSION\""
echo "INSTALLATION_PATH: \"$INSTALLATION_PATH\""
echo "WITHOUT_DOCKER: \"$WITHOUT_DOCKER\""
echo "WITHOUT_WM8960: \"$WITHOUT_WM8960\""
echo "WHEELS_DIRECTORY: \"$WHEELS_DIRECTORY\""
if [ -n "$WHEELS_DIRECTORY" ]; then
  echo "PROVIDED_WHEELS:"
  ls -l "$WHEELS_DIRECTORY"
fi
echo "----------------------------------------------"

VERSION_ENVIRONMENT="$INSTALLATION_PATH/${TARGET_VERSION}"

setup_virtualenv() {
  echo "Setting up Python virtual environment..."
  rm -rf "$VERSION_ENVIRONMENT"
  virtualenv --system-site-packages "$VERSION_ENVIRONMENT"
  echo "Virtual environment created at $VERSION_ENVIRONMENT."
}

echo "Installing dependencies..."
apt-get -fy install
apt-get -y update
apt-get -y install \
  accountsservice \
  dhcpcd \
  dnsmasq \
  git \
  hostapd \
  i2c-tools \
  ir-keytable \
  libasound2-dev \
  libcap-dev \
  libegl1 \
  libgl1 \
  libmtdev1 \
  libzbar0 \
  python3-alsaaudio \
  python3-apt \
  python3-dev \
  python3-gpiozero \
  python3-libcamera \
  python3-pip \
  python3-virtualenv \
  --no-install-recommends --no-install-suggests
if [ "$IS_RPI" = true ]; then
  apt-get -y install \
    python3-picamera2 \
    --no-install-recommends --no-install-suggests
else
  apt-get -y install \
    gcc \
    --no-install-recommends --no-install-suggests
fi
apt-get -y clean
apt-get -y autoremove

systemctl stop dnsmasq
systemctl disable dnsmasq

if id -u "$USERNAME" >/dev/null 2>&1; then
  echo "User $USERNAME already exists."
else
  echo "Creating user $USERNAME..."
  adduser --disabled-password --gecos "" "$USERNAME"
  echo "User $USERNAME created successfully."
fi

echo "Adding user $USERNAME to required groups..."
usermod -aG adm,audio,video,i2c,kmem,render "$USERNAME"
if [ "$IS_RPI" = true ]; then
  usermod -aG gpio,spi "$USERNAME"
fi

if grep -q "XDG_RUNTIME_DIR" "/home/$USERNAME/.bashrc"; then
  echo "XDG_RUNTIME_DIR already set in .bashrc"
else
  echo "Setting XDG_RUNTIME_DIR in /home/$USERNAME/.bashrc..."
  echo "export XDG_RUNTIME_DIR=/run/user/$(id -u "$USERNAME")" >>"/home/$USERNAME/.bashrc"
fi

setup_virtualenv

SOURCE="ubo-app${TARGET_VERSION:+==$TARGET_VERSION}"
echo "Installing ${SOURCE} in $VERSION_ENVIRONMENT..."
$VERSION_ENVIRONMENT/bin/python -m pip install${WHEELS_DIRECTORY:+ --pre --find-links="$WHEELS_DIRECTORY"} "$SOURCE" --force-reinstall | tee >(grep -c '^Collecting ' >"$INSTALLATION_PATH/.packages-count")

echo "${SOURCE} installed successfully in $VERSION_ENVIRONMENT."

UBO_APP_DIR=$($VERSION_ENVIRONMENT/bin/python -c 'import ubo_app; print(ubo_app.__path__[0])')

if [ -z "$WITHOUT_WM8960" ]; then
  echo "Installing WM8960 driver..."
  $UBO_APP_DIR/system/scripts/install_wm8960.sh
  echo "WM8960 driver installed successfully."
fi

if [ -z "$WITHOUT_DOCKER" ]; then
  echo "Installing Docker..."
  USERNAME=$USERNAME $UBO_APP_DIR/system/scripts/install_docker.sh
  echo "Docker installed successfully."
fi

rm -rf "$INSTALLATION_PATH/env"
echo "Linking $INSTALLATION_PATH/env to $VERSION_ENVIRONMENT..."
ln -s "$VERSION_ENVIRONMENT" "$INSTALLATION_PATH/env"
chown -R "$USERNAME:$USERNAME" "$INSTALLATION_PATH"
chmod -R 700 "$INSTALLATION_PATH"

echo "Bootstrapping ubo-app..."
"$INSTALLATION_PATH/env/bin/ubo-bootstrap"${IN_PACKER:+ --in-packer}
echo "Bootstrapping completed"

sleep 7

sudo XDG_RUNTIME_DIR=/run/user/$(id -u "$USERNAME") -u "$USERNAME" systemctl --user restart ubo-app || true
systemctl restart ubo-system || true
