#!/usr/bin/env bash

set -o errexit
set -o pipefail
set -o nounset

# Check for root privileges
if [ "$(id -u)" != "0" ]; then
  echo "This script must be run as root" 1>&2
  exit 1
fi

# Define the username
USERNAME_BASE='_tmp_'
COUNTER=0
while true; do
  USERNAME="${USERNAME_BASE}${COUNTER}"
  if ! id -u $USERNAME &>/dev/null; then
    break
  fi
  COUNTER=$((COUNTER+1))
done

# Create the user
useradd -m -s /bin/bash $USERNAME

# Set the password
while true; do
  PASSWORD=$(openssl rand -base64 6)
  if [[ $PASSWORD =~ [IilO] ]]; then
    continue
  fi
  break
done
echo "${USERNAME}:${PASSWORD}" | chpasswd
passwd --expire $USERNAME > /dev/null
printf "${USERNAME}:${PASSWORD}"

# Add the user to the sudo group
usermod -aG sudo $USERNAME

# Allow the user to run sudo without a password
echo "${USERNAME} ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/${USERNAME}

# Allow password authentication
sed -i 's/PasswordAuthentication no/PasswordAuthentication yes/g' /etc/ssh/sshd_config
systemctl restart ssh
