#!/usr/bin/env bash

set -e -o errexit

# Check for root privileges
if [ "$(id -u)" != "0" ]; then
  echo "This script must be run as root" 1>&2
  exit 1
fi

# Remove all temporary accounts
USERNAME_BASE='_tmp_'
for user in $(awk -F: '($3 >= 1000) && ($3 != 65534) {print $1}' /etc/passwd); do
  if [[ $user == $USERNAME_BASE* ]]; then
    userdel -r $user
    rm -f /etc/sudoers.d/$user
  fi
done
