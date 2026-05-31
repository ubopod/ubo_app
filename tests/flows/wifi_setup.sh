#!/bin/bash

IS_RPI=false

# Check if the script is running on a Raspberry Pi
if [ -e /etc/rpi-issue ]; then
  IS_RPI=true
fi

if [ "$IS_RPI" = true ]; then
  # Disconnect all active connections
  nmcli connection show --active | grep wifi | awk -F "  " '{print $1}' | while read conn; do
      nmcli connection down "$conn"
  done

  # Delete all Wi-Fi connections
  nmcli connection show | grep wifi | awk -F "  " '{print $1}' | while read conn; do
      nmcli connection delete "$conn"
  done

  echo "All Wi-Fi connections have been disconnected and deleted."
fi
