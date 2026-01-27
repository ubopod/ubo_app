# ZHA CLI

A command-line interface for managing Zigbee coordinators and devices using the [ZHA](https://github.com/zigpy/zha) library.

## Features

- **Coordinator Detection**: Automatically probe serial ports to detect Zigbee coordinators (EZSP, ZNP, deCONZ, ZiGate, XBee)
- **Network Management**: Start and stop Zigbee networks
- **Device Pairing**: Enable pairing mode to add new Zigbee devices
- **Device Control**: Turn on/off switches and lights

## Installation

```bash
pip install zha-cli
```

Or install from source:

```bash
git clone https://github.com/your-username/zha-cli.git
cd zha-cli
pip install -e .
```

## Usage

Run the CLI:

```bash
zha-cli
```

Or with verbose logging:

```bash
zha-cli -v
```

### Main Menu Options

1. **Probe for coordinators** - Scan serial ports for Zigbee coordinators
2. **Start network** - Connect to the selected coordinator and start the Zigbee network
3. **Pair device** - Enable pairing mode to add new devices
4. **List devices** - Show all paired Zigbee devices
5. **Control device** - Turn devices on/off
6. **Exit** - Shut down and exit

## Supported Coordinators

| Radio Type | Description |
|------------|-------------|
| EZSP | Silicon Labs EmberZNet (Elelabs, HUSBZB-1, Telegesis) |
| ZNP | Texas Instruments Z-Stack (CC253x, CC26x2, CC13x2) |
| deCONZ | dresden elektronik (ConBee I/II, RaspBee I/II) |
| ZiGate | ZiGate radios (PiZiGate, ZiGate USB-TTL, ZiGate WiFi) |
| XBee | Digi XBee Zigbee radios (Series 2, 2C, 3) |

## Requirements

- Python 3.12+
- A supported Zigbee coordinator connected via USB/serial

## Dependencies

- [zha](https://github.com/zigpy/zha) - Zigbee Home Automation library
- [rich](https://github.com/Textualize/rich) - Terminal UI library
- [pyserial](https://github.com/pyserial/pyserial) - Serial port access

## License

Apache-2.0
