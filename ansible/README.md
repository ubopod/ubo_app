# Ansible Playbooks for ubo-app Deployment

This directory contains Ansible playbooks and roles for deploying ubo-app to Raspberry Pi devices.

## Prerequisites

- Ansible installed (included in dev dependencies: `uv sync`)
- SSH access to target Raspberry Pi devices
- Target devices running Raspberry Pi OS (Debian Trixie) with Python 3.13+

## Quick Start

```bash
# Full deployment to a specific device
./scripts/build-and-deploy.sh --index=1 --ask-pass

# Quick update (wheels only, skip system setup)
./scripts/build-and-deploy.sh --index=1 --ask-pass --update-only
```

## Directory Structure

```
ansible/
├── ansible.cfg                 # Ansible configuration
├── inventory/
│   ├── hosts.yml               # Device inventory (ubo-pod-1, ubo-pod-2, etc.)
│   └── group_vars/all.yml      # Global variables (packages, groups, config)
├── playbooks/
│   ├── deploy.yml              # Full deployment playbook
│   ├── update.yml              # Quick update (wheels + restart only)
│   └── build-wheels.yml        # Local wheel building
├── roles/
│   └── ubo_app/
│       ├── defaults/main.yml   # Default role variables
│       ├── handlers/main.yml   # Service restart handlers
│       ├── tasks/              # Task files (see below)
│       └── templates/          # Jinja2 templates for services
└── scripts/
    └── build-and-deploy.sh     # Convenience wrapper script
```

## Wrapper Script

The `scripts/build-and-deploy.sh` script is the recommended way to run deployments.

### Usage

```bash
./scripts/build-and-deploy.sh [OPTIONS]
```

### Options

| Option | Description |
|--------|-------------|
| `--index=N` | Target specific device (ubo-pod-N). Without this, targets all devices. |
| `--update-only` | Quick update: only install wheels and restart services. Skips system setup. |
| `--no-docker` | Skip Docker CE installation |
| `--no-wm8960` | Skip WM8960 audio driver installation |
| `--skip-build` | Use existing wheels in `dist/`, don't rebuild |
| `--from-pypi` | Install ubo-app from PyPI instead of local wheels |
| `--offline` | Build wheels in offline mode (no network for uv) |
| `--ask-pass`, `-k` | Prompt for SSH and sudo passwords (use if no SSH keys) |
| `--verbose`, `-v` | Verbose output (show task details) |
| `--check` | Dry run mode (don't make changes) |
| `--diff` | Show file diffs for changes |

### Examples

```bash
# Full deployment to device 2 with password auth
./scripts/build-and-deploy.sh --index=2 --ask-pass

# Quick update with verbose output
./scripts/build-and-deploy.sh --index=1 --update-only -v

# Deploy without Docker or audio driver
./scripts/build-and-deploy.sh --index=1 --no-docker --no-wm8960

# Dry run to see what would change
./scripts/build-and-deploy.sh --index=1 --check --diff

# Use pre-built wheels, don't rebuild
./scripts/build-and-deploy.sh --index=1 --skip-build

# Install from PyPI instead of local build
./scripts/build-and-deploy.sh --index=1 --from-pypi
```

## Running Playbooks Directly

You can also run playbooks directly with `ansible-playbook`:

```bash
cd ansible

# Full deployment
uv run ansible-playbook playbooks/deploy.yml --limit ubo-pod-1 --ask-pass --ask-become-pass

# Quick update
uv run ansible-playbook playbooks/update.yml --limit ubo-pod-1 -e ubo_wheels_path=/path/to/wheels

# Build wheels locally
uv run ansible-playbook playbooks/build-wheels.yml
```

### Playbook Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ubo_username` | `ubo` | System user for running ubo-app |
| `ubo_installation_path` | `/opt/ubo` | Installation directory |
| `ubo_install_docker` | `true` | Whether to install Docker CE |
| `ubo_install_wm8960` | `true` | Whether to install WM8960 audio driver (RPi only) |
| `ubo_wheels_path` | `""` | Path to local wheel files |
| `ubo_target_version` | `""` | Specific version to install from PyPI |

Override variables with `-e`:

```bash
uv run ansible-playbook playbooks/deploy.yml -e ubo_install_docker=false -e ubo_username=myuser
```

## Deployment Tasks

The `ubo_app` role executes these tasks in order:

| Task File | Description |
|-----------|-------------|
| `preflight.yml` | Validate Debian, Python 3.13+, detect Raspberry Pi |
| `packages.yml` | Install APT packages, disable dnsmasq/dhcpcd |
| `user.yml` | Create ubo user, add to groups, set XDG_RUNTIME_DIR |
| `virtualenv.yml` | Create Python venv with --system-site-packages |
| `install_wheels.yml` | Copy wheels, pip install, create env symlink |
| `docker.yml` | Install Docker CE (optional) |
| `wm8960.yml` | Install WM8960 audio driver (optional, RPi only) |
| `bootstrap.yml` | Boot config, polkit rules, I2C/SPI, enable linger |
| `services.yml` | Deploy and enable systemd services |

## Inventory

Edit `inventory/hosts.yml` to configure your devices:

```yaml
all:
  children:
    ubo_pods:
      hosts:
        ubo-pod-1:
          ansible_host: ubo-development-pod-1  # Hostname or IP
          ansible_user: pi                      # SSH user
          ubo_pod_index: 1
        ubo-pod-2:
          ansible_host: 192.168.1.100          # Can use IP address
          ansible_user: pi
          ubo_pod_index: 2
```

## SSH Key Setup (Recommended)

For passwordless deployment, set up SSH keys:

```bash
# Generate SSH key if you don't have one
ssh-keygen -t ed25519

# Copy to each Pi
ssh-copy-id pi@ubo-development-pod-1
ssh-copy-id pi@ubo-development-pod-2
```

Then you can omit `--ask-pass`:

```bash
./scripts/build-and-deploy.sh --index=1
```

## Verification

After deployment, verify on the target device:

```bash
# Check services
systemctl status ubo-system
sudo -u ubo XDG_RUNTIME_DIR=/run/user/$(id -u ubo) systemctl --user status ubo-app

# Check user and groups
id ubo

# Check virtualenv
ls -la /opt/ubo/env

# Check boot config (RPi)
grep dtoverlay /boot/firmware/config.txt
```

## Troubleshooting

### SSH Connection Issues

```bash
# Test SSH connectivity
ssh pi@ubo-development-pod-1

# Check SSH config in ~/.ssh/config
Host ubo-development-pod-*
    User pi
    StrictHostKeyChecking no
```

### Permission Denied

Use `--ask-pass` and `--ask-become-pass` (handled by `-k` flag in wrapper):

```bash
./scripts/build-and-deploy.sh --index=1 --ask-pass
```

### Task Failures

Run with verbose output to see details:

```bash
./scripts/build-and-deploy.sh --index=1 -v      # Verbose
./scripts/build-and-deploy.sh --index=1 -vvv    # Very verbose
```

### WM8960 Audio Not Working

The blacklist for `snd_bcm2835` only takes effect after reboot:

```bash
ssh pi@ubo-development-pod-1 "sudo reboot"
```
