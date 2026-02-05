#!/usr/bin/env bash
#
# Convenience wrapper for building and deploying ubo-app via Ansible
#
# Usage:
#   ./scripts/build-and-deploy.sh                    # Full deploy to all devices
#   ./scripts/build-and-deploy.sh --index=1          # Deploy to specific device
#   ./scripts/build-and-deploy.sh --update-only      # Quick update (wheels + restart)
#   ./scripts/build-and-deploy.sh --no-docker        # Skip Docker installation
#   ./scripts/build-and-deploy.sh --no-wm8960        # Skip WM8960 audio driver
#   ./scripts/build-and-deploy.sh --skip-build       # Use existing wheels, don't rebuild
#   ./scripts/build-and-deploy.sh --from-pypi        # Install from PyPI instead of local wheels
#   ./scripts/build-and-deploy.sh --offline          # Build in offline mode

set -o errexit
set -o pipefail
set -o nounset

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANSIBLE_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_ROOT="$(dirname "$ANSIBLE_DIR")"
DIST_DIR="$PROJECT_ROOT/dist"

# Set Ansible config path
export ANSIBLE_CONFIG="$ANSIBLE_DIR/ansible.cfg"

# Default values
INDEX=""
UPDATE_ONLY=false
INSTALL_DOCKER=true
INSTALL_WM8960=true
SKIP_BUILD=false
FROM_PYPI=false
OFFLINE=false
ASK_PASS=false
EXTRA_ARGS=()

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --index=*)
            INDEX="${1#*=}"
            shift
            ;;
        --update-only)
            UPDATE_ONLY=true
            shift
            ;;
        --no-docker)
            INSTALL_DOCKER=false
            shift
            ;;
        --no-wm8960)
            INSTALL_WM8960=false
            shift
            ;;
        --skip-build)
            SKIP_BUILD=true
            shift
            ;;
        --from-pypi)
            FROM_PYPI=true
            SKIP_BUILD=true
            shift
            ;;
        --offline)
            OFFLINE=true
            shift
            ;;
        --ask-pass|-k)
            ASK_PASS=true
            shift
            ;;
        --verbose|-v)
            EXTRA_ARGS+=("-v")
            shift
            ;;
        --check)
            EXTRA_ARGS+=("--check")
            shift
            ;;
        --diff)
            EXTRA_ARGS+=("--diff")
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo ""
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --index=N       Target specific device (ubo-pod-N)"
            echo "  --update-only   Quick update (wheels + restart only)"
            echo "  --no-docker     Skip Docker installation"
            echo "  --no-wm8960     Skip WM8960 audio driver installation"
            echo "  --skip-build    Use existing wheels, don't rebuild"
            echo "  --from-pypi     Install from PyPI instead of local wheels"
            echo "  --offline       Build in offline mode (no network for uv)"
            echo "  --ask-pass, -k  Prompt for SSH password (if no SSH keys)"
            echo "  --verbose, -v   Verbose output"
            echo "  --check         Run in check mode (dry run)"
            echo "  --diff          Show diffs for changed files"
            exit 1
            ;;
    esac
done

# Change to ansible directory
cd "$ANSIBLE_DIR"

# Build wheels unless skipped
if [[ "$SKIP_BUILD" == false && "$FROM_PYPI" == false ]]; then
    echo "=== Building wheels ==="

    if [[ "$OFFLINE" == true ]]; then
        uv run --directory "$PROJECT_ROOT" ansible-playbook "$ANSIBLE_DIR/playbooks/build-wheels.yml" -e offline_mode=true
    else
        uv run --directory "$PROJECT_ROOT" ansible-playbook "$ANSIBLE_DIR/playbooks/build-wheels.yml"
    fi

    echo ""
fi

# Prepare ansible arguments
ANSIBLE_ARGS=()

# Add limit if index specified
if [[ -n "$INDEX" ]]; then
    ANSIBLE_ARGS+=("--limit" "ubo-pod-$INDEX")
fi

# Add extra variables
if [[ "$INSTALL_DOCKER" == false ]]; then
    ANSIBLE_ARGS+=("-e" "ubo_install_docker=false")
fi

if [[ "$INSTALL_WM8960" == false ]]; then
    ANSIBLE_ARGS+=("-e" "ubo_install_wm8960=false")
fi

# Add wheels path unless installing from PyPI
if [[ "$FROM_PYPI" == false ]]; then
    ANSIBLE_ARGS+=("-e" "ubo_wheels_path=$DIST_DIR")
fi

# Add ask-pass if needed
if [[ "$ASK_PASS" == true ]]; then
    ANSIBLE_ARGS+=("--ask-pass" "--ask-become-pass")
fi

# Add any extra args (verbose, check, diff)
if [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; then
    ANSIBLE_ARGS+=("${EXTRA_ARGS[@]}")
fi

# Choose playbook
if [[ "$UPDATE_ONLY" == true ]]; then
    PLAYBOOK="$ANSIBLE_DIR/playbooks/update.yml"
    echo "=== Running quick update ==="
else
    PLAYBOOK="$ANSIBLE_DIR/playbooks/deploy.yml"
    echo "=== Running full deployment ==="
fi

# Show what we're about to do
echo "Playbook: $PLAYBOOK"
echo "Arguments: ${ANSIBLE_ARGS[*]:-none}"
echo ""

# Run ansible
uv run --directory "$PROJECT_ROOT" ansible-playbook "$PLAYBOOK" "${ANSIBLE_ARGS[@]}"

echo ""
echo "=== Done ==="
