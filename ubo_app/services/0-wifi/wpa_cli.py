# ruff: noqa
"""
examples of cli commands:

wpa_cli -i wlan0 + command
command:
> list_networks # -> returns list of configured networks
> enable_network id # -> enables network
> disable_network id # -> disables network 
> remove_network id # -> removes network from wpa_supplicant.conf
> save_config # -> saves wpa_supplicant.conf
> reconfigure # -> reloads wpa_supplicant.conf
> status # -> returns status of current connection
> terminate # -> terminates wpa_supplicant
> scan # -> scans for networks
> scan_results # -> returns list of scanned networks
> add_network # -> returns id of new network
> set_network id ssid '"example_ssid"' # set ssid for WPA
> set_network id psk '"example_password"' # set password for WPA
> set_network id key_mgmt NONE # set key_mgmt for OPEN
> set_network id wep_key '"example_password"' # set password for WEP
> log_level DEBUG # -> sets log level to debug

>> The list_networks command in wpa_cli returns a list of c onfigured network 
blocks along with their network IDs. The columns returned by this command 
include the network ID, SSID, BSSID, flags, and other information about the 
networks.

The "flags" column provides information about the status of each network 
block. Some possible flag values that you might encounter include:

[DISABLED]: Indicates that the network block is currently disabled.
[CURRENT]: Indicates that the network block is the currently associated network.
[TEMP-DISABLED]: Indicates that the network block is temporarily disabled. This could happen due to connection failures.
[P2P-PERSISTENT]: Indicates that the network block is associated with a persistent P2P group.
[P2P-GO]: Indicates that the network block is acting as the Group Owner in a P2P connection.
[P2P-CLIENT]: Indicates that the network block is acting as a client in a P2P connection.
[P2P-DEVICE]: Indicates that the network block is a P2P device.
[P2P-FIND]: Indicates that the network block is in the process of finding P2P peers.
[P2P-PD]: Indicates that the network block is in the process of provisioning a P2P device.

For more information on wpa_cli commands, see:
https://www.qnx.com/developers/docs/6.5.0SP1.update/com.qnx.doc.neutrino_utilities/w/wpa_cli.html
http://hackerj.tistory.com/34
https://linux.die.net/man/8/wpa_cli

NOTES: 

(1) please make sure your userspace belongs to the netdev group on Raspberry Pi. 
Pi user is already a member of this group by default.

(2) To address issue with error:

CTRL-EVENT-ASSOC-REJECT status_code=16

That leads to WiFi getting blacklisted, add the following line to 

/etc/modprobe.d/brcmfmac.conf:

options brcmfmac roamoff=1

More info:
https://raspberrypi.stackexchange.com/questions/77144/rpi3-wireless-issue-ctrl-event-assoc-reject-status-code-16/140525#140525

"""

from pathlib import Path
import subprocess
from typing import Literal, TypedDict, Union
import logging.config
import re


class NetworkDescription(TypedDict):
    network_id: str
    ssid: str
    bssid: str
    flags: str


class WpaCliWrapper:
    """Wrapper class for wpa_cli commands.

    Attributes
    -----------
        interface: 'str'
            The network interface name to use for
            wpa_cli commands. Default is wlan0.
    """

    def __init__(self, interface='wlan0'):
        """initialize the class with default interface wlan0."""
        self.interface = interface
        self.logger = logging.getLogger('wpa_cli')

    def _run_system_command(self, command: Union[str, list[str]]) -> str:
        """Run the cli command as system commands.

        Parameters
        ----------
        command: Union[str, list[str]]
            The command to run. Can be a string or a list of strings.
            It uses the subprocess.run() method to run the command.

        Returns
        -------
        str: The output of the command.
        """
        try:
            IS_RPI = Path('/etc/rpi-issue').exists()
            if not IS_RPI:
                return ''
            result = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            self.logger.debug(f'Error: {e.stderr.strip()}')
            raise e

    def _run_command(self, command: Union[str, list[str]]) -> str:
        """Run the cli command as system commands.

        Parameters
        ----------
        command: Union[str, list[str]]
            The command to run. Can be a string or a list of strings.
            It uses the subprocess.run() method to run the command.
        """
        cmd = ['wpa_cli', '-i', self.interface, '-p', '/var/run/wpa_supplicant']
        if isinstance(command, str):
            cmd.append(command)
        elif isinstance(command, list):
            cmd.extend(command)
        self.logger.debug(f'Running command: {cmd}')
        return self._run_system_command(cmd)

    def generate_passphrase(self, ssid, password=None):
        # wpa_passphrase "ssid" passphrase
        cmd = ['wpa_passphrase', ssid, password]
        network = self._run_system_command(cmd)
        self.logger.debug(f'Generated network: {network}')
        psk = self._parse_psk(network)
        return psk

    def _parse_scan_results(self, results):
        """Parse the scan results into a list of dictionaries.

        Parameters
        ----------
        results: 'str'
            The raw results from the scan_results command.

        Returns
        -------
        networks: 'list[dict]'
            A list of dictionaries containing the parsed results.
            {
                'bssid': bssid,
                'frequency': frequency,
                'signal_level': signal_level,
                'flags': flags,
                'ssid': ssid
            }
        """
        networks = []
        if results:
            lines = results.split('\n')[2:]
            for line in lines:
                values = line.split()
                if len(values) >= 5:
                    bssid = values[0]
                    frequency = int(values[1])
                    signal_level = int(values[2])
                    flags = values[3].strip('[]').split('][')
                    ssid = values[4]

                    networks.append(
                        {
                            'bssid': bssid,
                            'frequency': frequency,
                            'signal_level': signal_level,
                            'flags': flags,
                            'ssid': ssid,
                        }
                    )

        return networks

    def _parse_list_networks(self, results: str) -> list[NetworkDescription]:
        """Parse the list_networks command results into a list of dictionaries.

        Parameters
        ----------
        results: 'str'
            The raw results from the list_networks command.

        Returns
        -------
        networks: 'list[dict]'
            A list of dictionaries containing the parsed results.
            {
                'network_id': network_id,
                'ssid': ssid,
                'bssid': bssid,
                'flags': flags
            }
        """
        lines = results.split('\n')
        networks = []
        for line in lines:
            parts = line.split('\t')
            if len(parts) >= 4:
                network_id, ssid, bssid, flags = parts[:4]
                networks.append(
                    {
                        'network_id': network_id,
                        'ssid': ssid,
                        'bssid': bssid,
                        'flags': flags,
                    }
                )
        self.logger.debug(f'List of networks: {networks}')
        return networks

    def _parse_list_interfaces(self, results: str) -> list[str]:
        """Parse the list_interfaces command results into a list of strings.

        Parameters
        ----------
        results: 'str'
            The raw results from the list_interfaces command.

        Returns
        -------
        interfaces: 'list[str]'
            A list of strings containing the names of
            available network interfaces.
        """

        lines = results.split('\n')[1:]
        interfaces = []
        for line in lines:
            interfaces.append(line.strip())
        return interfaces

    def _parse_status(self, status_output: str) -> dict:
        """Parse the status command results into a dictionary.

        Parameters
        ----------
        status_output: 'str'
            The raw results from the status command.

        Returns
        -------
        status: 'dict'
            A dictionary containing the parsed results.
            Here's an example of an output:
            {
                'bssid': 'a2:3d:cf:27:7e:0d',
                'freq': '5240',
                'ssid': 'example-guest',
                'id': '1',
                'mode': 'station',
                'pairwise_cipher': 'CCMP',
                'group_cipher': 'CCMP',
                'key_mgmt': 'WPA2-PSK',
                'wpa_state': 'COMPLETED',
                'p2p_device_address': 'e6:5f:01:e0:0a:f2',
                'address': 'e4:5f:01:e0:0a:f2',
                'uuid': '462bc09f-bab7-543a-98cc-0ef7006fe1e8',
                'ieee80211ac': '1'}
        """

        status_lines = status_output.split('\n')
        status = {}

        for line in status_lines:
            key, value = line.split('=', 1)
            status[key] = value

        return status

    def _parse_psk(self, cmd_output: str) -> str | None:
        """Parse the generate passphrase command results into a string.

        Parameters
        ----------
        cmd_output: 'str'
            The raw results from the generate_passphrase command.

        Returns
        -------
        psk: 'str'
            The psk string.
        """
        pattern = r'psk=(\w+)'
        match = re.search(pattern, cmd_output)

        if match:
            psk_value = match.group(1)
            print('Extracted PSK value:', psk_value)
            return psk_value
        else:
            print('PSK value not found in the input.')
            return None

    def scan(self):
        """Run the scan command."""
        return self._run_command('scan')

    def scan_results(self):
        """Run the scan_results command and parses the output."""
        raw_results = self._run_command('scan_results')
        return self._parse_scan_results(raw_results)

    def list_networks(self):
        """Run the list_networks command and parses the output."""
        IS_RPI = Path('/etc/rpi-issue').exists()
        if not IS_RPI:
            return [
                NetworkDescription(
                    network_id='test',
                    ssid='Hotel WiFi',
                    bssid='none',
                    flags='[CURRENT]',
                )
            ]
        raw_results = self._run_command('list_networks')
        return self._parse_list_networks(raw_results)

    def list_interfaces(self):
        """Run the list_interfaces command and parses the output."""
        raw_results = self._run_command('interface')
        return self._parse_list_interfaces(raw_results)

    def add_network(self):
        """Run the add_network command."""
        return self._run_command('add_network')

    def status(self):
        """Run the status command and parses the output."""
        raw_results = self._run_command('status')
        return self._parse_status(raw_results)

    def set_network(
        self,
        network_id,
        field: Literal['ssid', 'psk', 'auth_alg', 'key_mgmt', 'wep_key'],
        value,
    ):
        """Run the set_network command.

        Parameters
        ----------
        network_id: 'str'
            The network id to set the parameters for.
        field: Literal['ssid', 'psk', 'auth_alg', 'key_mgmt', 'wep_key']
            The parameter field to set.
        value: 'str'
            The value to set the field to.

        Returns
        -------
        bool: True if the command succeeded, False otherwise.
        """
        result = self._run_command(
            ['set_network', f'{network_id}', f'{field}', f'{value}']
        )
        if 'OK' == result:
            self.logger.debug(
                f'"set_network \
                        {network_id} {field} {value} " command succeeded!'
            )
            return True
        else:
            self.logger.error(
                f'"set_network \
                          {network_id} {field} {value} " command failed'
            )
            raise Exception(
                f'"set_network \
                            {network_id} {field} {value} " command failed'
            )

    def enable_network(self, network_id):
        """Run the enable_network command.

        Parameters
        ----------
        network_id: 'str'
            The network id to enable.
        """
        return self._run_command(['enable_network', f'{network_id}'])

    def select_network(self, network_id):
        """Run the select_network command.

        Parameters
        ----------
        network_id: 'str'
            The network id to enable.
        """
        return self._run_command(['select_network', f'{network_id}'])

    def disable_network(self, network_id):
        """Run the disable_network command.

        Parameters
        ----------
        network_id: 'str'
            The network id to disable.
        """
        return self._run_command(['disable_network', f'{network_id}'])

    def remove_network(self, network_id):
        """Run the remove_network command.

        Parameters
        ----------
        network_id: 'str'
            The network id to remove.
        """
        return self._run_command(['remove_network', f'{network_id}'])

    def clear_blacklist(self):
        """Run the clear_blacklist command."""
        return self._run_command(['blacklist', 'clear'])

    def check_blacklist(self):
        """Run the blacklist command."""
        return self._run_command(['blacklist'])

    def terminate(self):
        """Run the terminate command."""
        return self._run_command('terminate')

    def reconfigure(self):
        """Run the reconfigure command."""
        return self._run_command('reconfigure')

    def save_config(self):
        """Run the save_config command."""
        return self._run_command('save_config')

    def log_level(
        self,
        level: Literal['EXCESSIVE', 'MSGDUMP', 'DEBUG', 'INFO', 'WARNING', 'ERROR'],
    ):
        """Run the log_level command.

        Parameters
        ----------
        level: Literal['EXCESSIVE', 'MSGDUMP', 'DEBUG', 'INFO', 'WARNING', 'ERROR']
            The log level to set.
        """
        return self._run_command(['log_level', f'{level}'])

    # Add more methods as needed for other wpa_cli commands


if __name__ == '__main__':
    wrapper = WpaCliWrapper()

    scan_results = wrapper.scan_results()
    for network in scan_results:
        print(network)

    configured_networks = wrapper.list_networks()
    for network in configured_networks:
        print(network)

    available_interfaces = wrapper.list_interfaces()
    for interface in available_interfaces:
        print(interface)

    # wrapper.logger.info(wrapper.status())
    # psk = wrapper.generate_passphrase('earlplex-guest', 'hammerearlplex')
    # print(psk)
