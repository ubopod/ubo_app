#!/usr/bin/env bash
# Regenerate ubo_client.pb.{c,h} from ubo_client.proto via nanopb.
#
# The generated files are committed (so the normal build / ESP-IDF needs no
# Python toolchain); run this only when ubo_client.proto changes. nanopb auto-
# loads the sibling ubo_client.options (global pointer/malloc mode).
set -euo pipefail
cd "$(dirname "$0")"
GEN=../../third_party/nanopb/generator/nanopb_generator.py
uv run --with protobuf --with grpcio-tools python "$GEN" ubo_client.proto -I .
echo "Regenerated ubo_client.pb.{c,h}"
