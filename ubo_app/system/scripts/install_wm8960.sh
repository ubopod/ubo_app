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
  echo "Sorry, this drivers only works on raspberry pi"
  exit 1
fi

apt-get -fy install
apt-get -y update
apt-get -y install \
  raspberrypi-kernel-headers \
  dkms \
  git \
  i2c-tools \
  libasound2-plugins \
  --no-install-recommends --no-install-suggests
apt-get -y clean
apt-get -y autoremove

#download the archive
rm -rf wm8960-driver
git clone https://github.com/ubopod/WM8960-Audio-HAT wm8960-driver

cd wm8960-driver

# locate currently installed kernels (may be different to running kernel if
# it's just been updated)
kernels=$(ls /lib/modules)

function install_module {
  ver="1.0"
  # we create a dir with this version to ensure that 'dkms remove' won't delete
  # the sources during kernel updates
  marker="0.0.0"

  src=$1
  mod=$2

  if [[ -d /var/lib/dkms/$mod/$ver/$marker ]]; then
    rmdir /var/lib/dkms/$mod/$ver/$marker
  fi

  if [[ -e /usr/src/$mod-$ver || -e /var/lib/dkms/$mod/$ver ]]; then
    dkms remove --force -m $mod -v $ver --all || true
    rm -rf /usr/src/$mod-$ver
  fi
  mkdir -p /usr/src/$mod-$ver
  cp -a $src/* /usr/src/$mod-$ver/
  dkms add -m $mod -v $ver
  for kernel in $kernels; do
    # It works for kernels greater than or equal 6.12
    if [ "$(printf '%s\n' "$kernel" "6.12" | sort -V | head -n1)" = "$kernel" ]; then
      continue
    fi
    dkms build "$kernel" -k "$kernel" --kernelsourcedir "/lib/modules/$kernel/build" -m $mod -v $ver &&
      dkms install --force "$kernel" -k "$kernel" -m $mod -v $ver
  done

  mkdir -p /var/lib/dkms/$mod/$ver/$marker
}

install_module "./" "wm8960-soundcard"

# install dtbos
cp wm8960-soundcard.dtbo /boot/overlays

#set kernel modules
grep -q "^i2c-dev$" /etc/modules ||
  echo "i2c-dev" >>/etc/modules
grep -q "^snd-soc-wm8960$" /etc/modules ||
  echo "snd-soc-wm8960" >>/etc/modules
grep -q "^snd-soc-wm8960-soundcard$" /etc/modules ||
  echo "snd-soc-wm8960-soundcard" >>/etc/modules

# set modprobe blacklist
grep -q "^blacklist snd_bcm2835$" /etc/modprobe.d/raspi-blacklist.conf ||
  echo "blacklist snd_bcm2835" >>/etc/modprobe.d/raspi-blacklist.conf

#set dtoverlays
sed -i -e 's:#dtparam=i2s=on:dtparam=i2s=on:g' /boot/firmware/config.txt || true
sed -i -e 's:#dtparam=i2c_arm=on:dtparam=i2c_arm=on:g' /boot/firmware/config.txt || true
grep -q "^dtoverlay=i2s-mmap$" /boot/firmware/config.txt ||
  echo "dtoverlay=i2s-mmap" >>/boot/firmware/config.txt

grep -q "^dtparam=i2s=on$" /boot/firmware/config.txt ||
  echo "dtparam=i2s=on" >>/boot/firmware/config.txt

grep -q "^dtoverlay=wm8960-soundcard$" /boot/firmware/config.txt ||
  echo "dtoverlay=wm8960-soundcard" >>/boot/firmware/config.txt

#install config files
mkdir -p /etc/wm8960-soundcard
cp *.conf /etc/wm8960-soundcard
cp *.state /etc/wm8960-soundcard

#set service
cp wm8960-soundcard /usr/bin/
chmod -x wm8960-soundcard.service
cp wm8960-soundcard.service /lib/systemd/system/
systemctl enable wm8960-soundcard.service

#cleanup
cd ..
rm -rf wm8960-driver

echo "------------------------------------------------------"
echo "Please reboot your raspberry pi to apply all settings"
echo "Enjoy!"
echo "------------------------------------------------------"
