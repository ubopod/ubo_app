#!/usr/bin/env bash
#
# First-boot loader for Docker images baked into the device image.
#
# The CI image build (scripts/packer) downloads selected images to tarballs
# under BUNDLE_DIR. The Docker daemon is not running during the QEMU chroot
# build, so the tarballs are loaded here on first boot — once dockerd is up —
# and then removed. The accompanying systemd unit disables itself afterwards.

set -o errexit
set -o nounset
set -o pipefail

BUNDLE_DIR="/var/lib/ubo/bundled-docker-images"

shopt -s nullglob
tarballs=("$BUNDLE_DIR"/*.tar)

if [ ${#tarballs[@]} -eq 0 ]; then
  echo "No bundled Docker image tarballs in $BUNDLE_DIR; nothing to load."
else
  for tarball in "${tarballs[@]}"; do
    echo "Loading bundled Docker image from $tarball..."
    docker load -i "$tarball"
    rm -f "$tarball"
    echo "Loaded and removed $tarball."
  done
fi

# Tidy up: drop the (now empty) bundle dir and disable this one-shot so it
# never runs again.
rmdir "$BUNDLE_DIR" 2>/dev/null || true
systemctl disable load-bundled-docker-images.service || true
