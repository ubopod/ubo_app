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
  echo "The USERNAME environment variable is not set" 1>&2
  exit 1
fi

# Remove all temporary accounts
userdel -r $USERNAME
rm -f /etc/sudoers.d/$USERNAME
