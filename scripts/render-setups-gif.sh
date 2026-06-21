#!/usr/bin/env bash
# Render docs/assets/setups.gif — the three-setups README demo.
# Preps creds-free state (central configs + a pre-built central index), runs
# VHS, then cleans the transient configs. Idempotent.
#   ./scripts/render-setups-gif.sh    (needs: vhs, a synced .venv)
set -euo pipefail
cd "$(dirname "$0")/.."

CENTRAL=/tmp/ckg-setups-demo/central
MS=examples/microservices

cleanup() { rm -rf "$MS"/*/ckg.yaml "$MS"/*/.ckg examples/fastapi-shop/.ckg /tmp/ckg-setups-demo; }
trap cleanup EXIT

rm -rf /tmp/ckg-setups-demo "$MS"/*/.ckg examples/fastapi-shop/.ckg
# NOTE: these demo services live inside this git repo, so they share one git
# remote -> one repo_key. Hosting them ALL under a single central_root would
# collide them. So only `orders` is hosted centrally (for the act-2 demo); the
# other services index in-repo (distinct .ckg). The act-3 workspace then reads
# 3 in-repo + 1 central index, no collision.
for s in web gateway payments; do uv run ckg index "$MS/$s" >/dev/null; done
printf 'store:\n  central_root: %s\n' "$CENTRAL" > "$MS/orders/ckg.yaml"
uv run ckg index "$MS/orders" >/dev/null

vhs docs/assets/setups.tape
echo "→ wrote docs/assets/setups.gif"
