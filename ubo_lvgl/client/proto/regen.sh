#!/usr/bin/env bash
# Regenerate ubo_client.pb.{c,h} from ubo_client.proto via nanopb.
#
# The generated files are gitignored (not committed) — run this whenever
# ubo_client.proto changes, or via `uv run poe proto:lvgl:generate` (also part
# of the umbrella `poe proto`). The ESP32/desktop C builds themselves still
# need no Python toolchain — only regenerating the proto does. nanopb auto-
# loads the sibling ubo_client.options (global pointer/malloc mode).
set -euo pipefail
cd "$(dirname "$0")"
GEN=../../third_party/nanopb/generator/nanopb_generator.py
uv run --with protobuf --with grpcio-tools python "$GEN" ubo_client.proto -I .
echo "Regenerated ubo_client.pb.{c,h}"
