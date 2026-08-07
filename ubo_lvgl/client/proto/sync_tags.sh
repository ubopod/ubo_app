#!/usr/bin/env bash
# sync_tags.sh — keep the LVGL C client's curated proto oneof tags in lockstep
# with ubo-core's generated proto.
#
# The curated proto (ubo_lvgl/client/proto/ubo_client.proto) hard-codes the
# Action/Event oneof tag numbers. ubo-core assigns those tags by ALPHABETICAL
# POSITION in the full sorted Action/Event list (generate_proto.py:
# `enumerate(sorted(generator.actions), 1)`), so adding ANY new action/event
# upstream silently shifts the tags of everything after it. Wrong tags →
# DispatchAction returns HTTP 200 + grpc-status 0 but the WRONG action fires.
#
# This script NEVER hand-computes tags. It reads the freshly generated
# ubo_app/rpc/proto/ubo/v1/ubo.proto (the source of truth) and diffs every
# oneof member the curated proto declares against it.
#
# Usage:
#   sync_tags.sh [REPO_ROOT]          # check only; exit 1 if drifted
#   sync_tags.sh [REPO_ROOT] --write  # apply the new tags to the curated proto
#
# PREREQUISITE: regenerate the core proto first so ubo.proto is current:
#   uv run poe proto:generate:raw
set -euo pipefail

WRITE=0
ROOT=""
for arg in "$@"; do
  case "$arg" in
    --write) WRITE=1 ;;
    *) ROOT="$arg" ;;
  esac
done
ROOT="${ROOT:-$(pwd)}"

CORE="$ROOT/ubo_app/rpc/proto/ubo/v1/ubo.proto"
CUR="$ROOT/ubo_lvgl/client/proto/ubo_client.proto"

[ -f "$CUR" ] || { echo "ERROR: curated proto not found: $CUR" >&2; exit 2; }
if [ ! -f "$CORE" ]; then
  echo "ERROR: generated core proto not found: $CORE" >&2
  echo "       Run: uv run poe proto:generate:raw" >&2
  exit 2
fi

# Extract members of ONLY the `action`, `event` and `assistant_trigger_source_union`
# oneofs. Those are the blocks whose field NAMES match core exactly and whose
# tags are position-derived (and therefore drift). The `basic_type` /
# `props_value` oneofs are intentionally excluded: their names are renamed to
# dodge C keyword clashes and their tags are stable local conventions, not
# core-position-derived.
#
# assistant_trigger_source_union is numbered by the same alphabetical rule, over
# the *TriggerSource classes rather than the actions — so adding a new trigger
# source upstream silently renumbers wake_phrase_trigger_source here.
members="$(awk '
  /oneof[ \t]+(action|event|assistant_trigger_source_union)[ \t]*\{/ { inblk=1; next }
  inblk && /^[ \t]*\}/                { inblk=0 }
  inblk && /= *[0-9]+ *;/             {
    field=$2; tag=$(NF);
    gsub(/[^0-9]/,"",tag);
    print field" "tag
  }
' "$CUR")"

[ -n "$members" ] || { echo "ERROR: no oneof members parsed from $CUR" >&2; exit 2; }

fail=0
updates=""
printf '%-40s %-10s %-10s %s\n' "FIELD" "CURATED" "CORE" "STATUS"
printf '%-40s %-10s %-10s %s\n' "-----" "-------" "----" "------"
while read -r field cur_tag; do
  [ -n "$field" ] || continue
  core_tag="$(grep -oE "[ \t]${field} = [0-9]+;" "$CORE" | grep -oE '[0-9]+' | head -1 || true)"
  if [ -z "$core_tag" ]; then
    printf '%-40s %-10s %-10s %s\n' "$field" "$cur_tag" "?" "MISSING-IN-CORE"
    fail=1
  elif [ "$core_tag" = "$cur_tag" ]; then
    printf '%-40s %-10s %-10s %s\n' "$field" "$cur_tag" "$core_tag" "ok"
  else
    printf '%-40s %-10s %-10s %s\n' "$field" "$cur_tag" "$core_tag" "DRIFT"
    fail=1
    updates="$updates$field $cur_tag $core_tag\n"
  fi
done <<< "$members"

if [ "$fail" -eq 0 ]; then
  echo
  echo "RESULT: all curated oneof tags in sync with core."
  exit 0
fi

if [ "$WRITE" -ne 1 ]; then
  echo
  echo "RESULT: DRIFT detected. Re-run with --write to patch $CUR, then run regen.sh."
  exit 1
fi

# Apply: replace ` <field> = <old>;` with ` <field> = <new>;` in the curated proto.
echo
echo "Applying updates to $CUR ..."
printf '%b' "$updates" | while read -r field old new; do
  [ -n "$field" ] || continue
  # macOS/BSD sed in-place; the oneof member is ` <field> = <tag>;` (one leading
  # space after the type name), so a literal space anchors the match portably.
  sed -i.bak -E "s/ ${field} = ${old};/ ${field} = ${new};/" "$CUR"
  echo "  $field: $old -> $new"
done
rm -f "$CUR.bak"
echo
echo "Done. Now regenerate nanopb output:"
echo "  bash $ROOT/ubo_lvgl/client/proto/regen.sh"
echo "Then re-run this script (no --write) to confirm, rebuild, and reflash."
