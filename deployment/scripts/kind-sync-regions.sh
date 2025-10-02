#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME=${KIND_CLUSTER_NAME:-flight-reader}
DATASET_PATH=${1:-deployment/data/regions.geojson}
TARGET_DIR=${TARGET_DIR:-/opt/flight-reader/regions}
TARGET_FILE=${TARGET_FILE:-regions.geojson}

if [[ ! -f "$DATASET_PATH" ]]; then
  echo "Dataset not found: $DATASET_PATH" >&2
  exit 1
fi


KIND_BIN=${KIND_BIN:-}
if [[ -z "$KIND_BIN" ]]; then
  if command -v kind >/dev/null 2>&1; then
    KIND_BIN=$(command -v kind)
  elif [[ -x "$HOME/bin/kind" ]]; then
    KIND_BIN="$HOME/bin/kind"
  else
    echo "kind CLI not found (set KIND_BIN or add to PATH)" >&2
    exit 1
  fi
fi

mapfile -t NODES < <("$KIND_BIN" get nodes --name "$CLUSTER_NAME")
if [[ ${#NODES[@]} -eq 0 ]]; then
  echo "No nodes found for cluster $CLUSTER_NAME" >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "docker CLI not found" >&2
  exit 1
fi

for node in "${NODES[@]}"; do
  echo "Syncing $DATASET_PATH to $node:$TARGET_DIR/$TARGET_FILE"
  docker exec "$node" mkdir -p "$TARGET_DIR"
  docker cp "$DATASET_PATH" "$node":"$TARGET_DIR/$TARGET_FILE"

done

echo "Regions dataset synced to kind nodes."
