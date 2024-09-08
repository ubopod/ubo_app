#!/usr/bin/env bash

set -o xtrace
set -o errexit
set -o pipefail
set -o nounset

USERNAME=${USERNAME:-"ubo"}
UPDATE=${UPDATE:-false}
ALPHA=${ALPHA:-false}
WITH_DOCKER=${WITH_DOCKER:-false}
IN_PACKER=false
SOURCE=${SOURCE:-"ubo-app"}

export DEBIAN_FRONTEND=noninteractive

# Parse arguments
for arg in "$@"
do
    case $arg in
        --update)
        UPDATE=true
        shift # Remove --update from processing
        ;;
        --alpha)
        ALPHA=true
        shift # Remove --alpha from processing
        ;;
        --with-docker)
        WITH_DOCKER=true
        shift # Remove --with-docker from processing
        ;;
        --in-packer)
        IN_PACKER=true
        shift # Remove --in-packer from processing
        ;;
        --source=*)
        SOURCE="${arg#*=}"
        shift # Remove --source from processing
        ;;
        *)
        # Unknown option
        ;;
    esac
done

echo "----------------------------------------------"
echo "Parameters:"
echo "UPDATE: $UPDATE"
echo "ALPHA: $ALPHA"
echo "WITH_DOCKER: $WITH_DOCKER"
echo "SOURCE: $SOURCE"
echo "----------------------------------------------"

# Check for root privileges
if [ "$(id -u)" != "0" ]; then
  echo "This script must be run as root" 1>&2
  exit 1
fi

# Define the username
if [ -z "${USERNAME}" ]; then
  USERNAME="ubo"
fi

# Create the user
adduser --disabled-password --gecos "" $USERNAME || true
usermod -aG adm,audio,video,gpio,i2c,spi,kmem,render $USERNAME

echo "User $USERNAME created successfully."

echo "export XDG_RUNTIME_DIR=/run/user/$(id -u $USERNAME)" >> /home/$USERNAME/.bashrc

# Install required packages
apt-get -y update
apt-get -y upgrade
apt-get -y install \
  accountsservice \
  git \
  i2c-tools \
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
  python3-picamera2 \
  python3-pip \
  python3-virtualenv \
  --no-install-recommends --no-install-suggests
apt-get -y clean

# Enable I2C and SPI
set +o errexit
raspi-config nonint do_i2c 0
raspi-config nonint do_spi 0
set -o errexit

# Define the installation path
INSTALLATION_PATH=${INSTALLATION_PATH:-"/opt/ubo"}

# Create the installation path
rm -rf "$INSTALLATION_PATH/env"
virtualenv --system-site-packages "$INSTALLATION_PATH/env"

# Install the latest version of ubo-app
if [ "$UPDATE" = true ]; then
  if [ "$ALPHA" = true ]; then
    "$INSTALLATION_PATH/env/bin/python" -m pip install --pre --no-index --upgrade --find-links "$INSTALLATION_PATH/_update/" "$SOURCE"[default]
  else
    "$INSTALLATION_PATH/env/bin/python" -m pip install --no-index --upgrade --find-links "$INSTALLATION_PATH/_update/" "$SOURCE"[default]
  fi
else
  if [ "$ALPHA" = true ]; then
    "$INSTALLATION_PATH/env/bin/python" -m pip install --pre "$SOURCE"[default] | grep -c '^Collecting ' > $INSTALLATION_PATH/.packages-count
  else
    # Count number of Collecting instances
    "$INSTALLATION_PATH/env/bin/python" -m pip install "$SOURCE"[default] | grep -c '^Collecting ' > $INSTALLATION_PATH/.packages-count
  fi
fi

# Set the ownership of the installation path
chown -R $USERNAME:$USERNAME "$INSTALLATION_PATH"
chmod -R 700 "$INSTALLATION_PATH"

# Bootstrap the application
UBO_LOG_LEVEL=INFO "$INSTALLATION_PATH/env/bin/bootstrap"${WITH_DOCKER:+ --with-docker}${IN_PACKER:+ --in-packer}
echo "Bootstrapping completed"

if [ "$UPDATE" = true ]; then
  # Remove the update directory
  rm -rf "$INSTALLATION_PATH/_update"
fi

if [ "$IN_PACKER" = true ]; then
  exit 0
else
  # The audio driver needs a reboot to work
  reboot
fi
