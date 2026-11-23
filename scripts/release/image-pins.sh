#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# image-pins.sh — resolve the digests of the five first-party images of a release
# tag and write them as the runtime bundle's IMAGES file (R-0460).
#
# Usage: image-pins.sh <vX.Y.Z> <out-file>
#
# install.sh and update.sh pin "<image>:X.Y.Z@sha256:<digest>" from IMAGES. The file
# is listed in MANIFEST.sha256 and so sits under the minisign signature of
# SHA256SUMS; a tag on ghcr can be moved, the pinned digest cannot. A digest only
# gets in once the keyless cosign signature docker.yml made for THIS tag verifies
# on it, so an image pushed under the tag after the build is never what a host pins.
# docker.yml runs in parallel on the tag push, so the script polls until each image
# is pushed and signed.
#
# Exit 0 = IMAGES written · 1 = an image missing, unsigned or with a malformed
# digest, no IMAGES left behind · 2 = usage.
set -euo pipefail
# The tag check below uses [0-9]; under de_DE.UTF-8 a bash range matches more.
export LC_ALL=C

if [[ $# -ne 2 || ! "${1:-}" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ || -z "${2:-}" ]]; then
  echo "usage: image-pins.sh <vX.Y.Z> <out-file>" >&2
  exit 2
fi
TAG="$1"
OUT="$2"
VER="${TAG#v}"
BASE="ghcr.io/admincave/adminhelper"
SIGNER="https://github.com/${GITHUB_REPOSITORY:-AdminCave/AdminHelper}/.github/workflows/docker.yml@refs/tags/${TAG}"
TRIES="${AH_PIN_TRIES:-20}"
PAUSE="${AH_PIN_SLEEP:-30}"

tmp="$(mktemp "${OUT}.XXXXXX")"
trap 'rm -f "$tmp"' EXIT

for pair in SERVER_IMAGE:server GATEWAY_IMAGE:gateway FRPS_IMAGE:frps \
            CA_ISSUER_IMAGE:ca-issuer MONITORING_IMAGE:monitoring; do
  key="${pair%%:*}"
  img="${pair#*:}"
  pinned=""
  why="not found on ghcr"
  for ((i = 1; i <= TRIES; i++)); do
    digest="$(docker buildx imagetools inspect "${BASE}/${img}:${VER}" --format '{{json .Manifest}}' 2>/dev/null \
      | jq -r '.digest // empty' 2>/dev/null || true)"
    if [[ -n "$digest" ]]; then
      if [[ ! "$digest" =~ ^sha256:[0-9a-f]{64}$ ]]; then
        echo "::error::${img}:${VER} resolved to a malformed digest '${digest}'" >&2
        exit 1
      fi
      if err="$(cosign verify --certificate-identity "$SIGNER" \
          --certificate-oidc-issuer https://token.actions.githubusercontent.com \
          "${BASE}/${img}@${digest}" 2>&1 >/dev/null)"; then
        pinned="$digest"
        break
      fi
      why="has no valid signature of ${SIGNER} on ${digest}: ${err##*$'\n'}"
    fi
    if ((i < TRIES)); then sleep "$PAUSE"; fi
  done
  if [[ -z "$pinned" ]]; then
    echo "::error::${img}:${VER} ${why} — docker.yml red or still running?" >&2
    exit 1
  fi
  printf '%s=%s/%s:%s@%s\n' "$key" "$BASE" "$img" "$VER" "$pinned" >> "$tmp"
  echo "ok: ${img}:${VER}@${pinned}"
done

chmod 0644 "$tmp"
mv "$tmp" "$OUT"
trap - EXIT
