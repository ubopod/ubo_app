#!/usr/bin/env bash

set -o errexit
set -o pipefail
set -o nounset

# Check for root privileges
if [ "$(id -u)" != "0" ]; then
  echo "This script must be run as root" 1>&2
  exit 1
fi

# Check if the username is set
if [ -z ${USERNAME+set} ]; then
  USERNAME_BASE='user'
  COUNTER=1
  while true; do
    USERNAME="${USERNAME_BASE}${COUNTER}"
    if ! id -u $USERNAME &>/dev/null; then
      break
    fi
    COUNTER=$((COUNTER+1))
  done

  # Create the user
  useradd -m -s /bin/bash $USERNAME
fi

# Check if the password is set
if [ -z ${PASSWORD+set} ]; then
  while true; do
    PASSWORD=$(openssl rand -base64 6)
    if [[ $PASSWORD =~ [IilO] ]]; then
      continue
    fi
    break
  done
fi
echo "${USERNAME}:${PASSWORD}" | chpasswd
printf "${USERNAME}:${PASSWORD}"

# Allow password authentication
sed -i 's/PasswordAuthentication no/PasswordAuthentication yes/g' /etc/ssh/sshd_config
systemctl restart ssh
