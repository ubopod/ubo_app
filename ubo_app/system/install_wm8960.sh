#!/usr/bin/env bash

set -o xtrace
set -o errexit
set -o pipefail
set -o nounset

if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root (use sudo)" 1>&2
   exit 1
fi

if [ ! -f /etc/rpi-issue ]; then
  echo "Sorry, this drivers only works on raspberry pi"
  exit 1
fi


#download the archive
git clone https://github.com/waveshare/WM8960-Audio-HAT
cd WM8960-Audio-HAT

# install dtbos
#cp wm8960-soundcard.dtbo /boot/overlays


#set kernel modules
grep -q "^i2c-dev$" /etc/modules || \
  echo "i2c-dev" >> /etc/modules  
grep -q "^snd-soc-wm8960$" /etc/modules || \
  echo "snd-soc-wm8960" >> /etc/modules  
grep -q "^snd-soc-wm8960-soundcard$" /etc/modules || \
  echo "snd-soc-wm8960-soundcard" >> /etc/modules  

# set modprobe blacklist
grep -q "^blacklist snd_bcm2835$" /etc/modprobe.d/raspi-blacklist.conf || \
  echo "blacklist snd_bcm2835" >> /etc/modprobe.d/raspi-blacklist.conf
  
#set dtoverlays
sed -i -e 's:#dtparam=i2s=on:dtparam=i2s=on:g'  /boot/config.txt || true
sed -i -e 's:#dtparam=i2c_arm=on:dtparam=i2c_arm=on:g'  /boot/config.txt || true
grep -q "^dtoverlay=i2s-mmap$" /boot/config.txt || \
  echo "dtoverlay=i2s-mmap" >> /boot/config.txt

grep -q "^dtparam=i2s=on$" /boot/config.txt || \
  echo "dtparam=i2s=on" >> /boot/config.txt

grep -q "^dtoverlay=wm8960-soundcard$" /boot/config.txt || \
  echo "dtoverlay=wm8960-soundcard" >> /boot/config.txt
  
#install config files
mkdir -p /etc/wm8960-soundcard
cp *.conf /etc/wm8960-soundcard
cp *.state /etc/wm8960-soundcard

#set service 
cp wm8960-soundcard /usr/bin/
chmod -x wm8960-soundcard.service
cp wm8960-soundcard.service /lib/systemd/system/
systemctl enable  wm8960-soundcard.service 

cd ..
rm -rf WM8960-Audio-HAT

echo "------------------------------------------------------"
echo "Please reboot your raspberry pi to apply all settings"
echo "Enjoy!"
echo "------------------------------------------------------"
