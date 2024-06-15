#!/bin/bash

# Disconnect all active connections
nmcli connection show --active | grep wifi | awk '{print $1}' | while read conn; do
    nmcli connection down "$conn"
done

# Delete all Wi-Fi connections
nmcli connection show | grep wifi | awk '{print $1}' | while read conn; do
    nmcli connection delete "$conn"
done

echo "All Wi-Fi connections have been disconnected and deleted."
