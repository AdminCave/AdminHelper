#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# image_pins_test.sh — hermetic test for scripts/release/image-pins.sh (R-0460).
#
# docker and cosign are stubs on PATH: the docker stub answers
# `buildx imagetools inspect` from a per-image digest file, the cosign stub logs
# its arguments and fails for images marked unsigned (or for the first N calls of
# an image marked late). The script is a RELEASE GATE: every red case asserts the
# exit code, the image it names AND that no IMAGES file was left behind.
#
# Run: bash scripts/tests/image_pins_test.sh

set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
PINS="$HERE/../release/image-pins.sh"

PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

command -v jq >/dev/null || { echo "image_pins_test: jq missing"; exit 75; }

IMGS="server gateway frps ca-issuer monitoring"
hex() { printf '%064d' "$1"; }

BIN="$WORK/bin"; mkdir -p "$BIN"
cat > "$BIN/docker" <<'STUB'
#!/usr/bin/env bash
# docker buildx imagetools inspect <ref> --format ...
[ "$1 $2 $3" = "buildx imagetools inspect" ] || { echo "docker stub: unexpected $*" >&2; exit 64; }
ref="$4"; img="${ref##*/}"; img="${img%%:*}"
[ -f "$STUB/digest-$img" ] || { echo "ERROR: $ref: not found" >&2; exit 1; }
printf '{"mediaType":"application/vnd.oci.image.index.v1+json","digest":"%s"}\n' "$(cat "$STUB/digest-$img")"
STUB
cat > "$BIN/cosign" <<'STUB'
#!/usr/bin/env bash
echo "$*" >> "$STUB/cosign.log"
ref="${*: -1}"; img="${ref##*/}"; img="${img%%@*}"
if [ -f "$STUB/unsigned-$img" ]; then echo "Error: no matching signatures" >&2; exit 1; fi
if [ -f "$STUB/late-$img" ]; then
  n=$(cat "$STUB/late-$img")
  if [ "$n" -gt 0 ]; then echo $((n - 1)) > "$STUB/late-$img"; echo "Error: no signatures found" >&2; exit 1; fi
fi
exit 0
STUB
chmod +x "$BIN/docker" "$BIN/cosign"

# setup <name> — a stub dir where every image resolves to a distinct valid digest.
setup() {
  STUB="$WORK/$1"; mkdir -p "$STUB"
  local i=1 img
  for img in $IMGS; do hex "$i" | sed 's/^/sha256:/' > "$STUB/digest-$img"; i=$((i + 1)); done
  export STUB
}

# run <args...> — runs the script; sets RC and LOG.
run() {
  LOG="$STUB/run.log"
  PATH="$BIN:$PATH" AH_PIN_TRIES=3 AH_PIN_SLEEP=0 GITHUB_REPOSITORY=AdminCave/AdminHelper \
    bash "$PINS" "$@" > "$LOG" 2>&1
  RC=$?
}

# red <name> <expect-substring> — exit 1, the substring in the output, no IMAGES, no temp file.
red() {
  if [ "$RC" -ne 1 ]; then bad "$1: exit $RC, want 1"; sed 's/^/       /' "$LOG"; return; fi
  if ! grep -qF -- "$2" "$LOG"; then bad "$1: output lacks '$2'"; sed 's/^/       /' "$LOG"; return; fi
  if [ -e "$STUB/IMAGES" ]; then bad "$1: IMAGES left behind"; return; fi
  if [ "$(find "$STUB" -name 'IMAGES.*' | wc -l)" -ne 0 ]; then bad "$1: temp file left behind"; return; fi
  ok "$1"
}

# ── 1: all five signed → IMAGES with five pinned lines, signer of this tag ──
setup good
run v1.2.3 "$STUB/IMAGES"
WANT="SERVER_IMAGE=ghcr.io/admincave/adminhelper/server:1.2.3@sha256:$(hex 1)
GATEWAY_IMAGE=ghcr.io/admincave/adminhelper/gateway:1.2.3@sha256:$(hex 2)
FRPS_IMAGE=ghcr.io/admincave/adminhelper/frps:1.2.3@sha256:$(hex 3)
CA_ISSUER_IMAGE=ghcr.io/admincave/adminhelper/ca-issuer:1.2.3@sha256:$(hex 4)
MONITORING_IMAGE=ghcr.io/admincave/adminhelper/monitoring:1.2.3@sha256:$(hex 5)"
if [ "$RC" -eq 0 ] && [ "$(cat "$STUB/IMAGES" 2>/dev/null)" = "$WANT" ]; then
  ok "all signed -> IMAGES with five digest pins"
else
  bad "all signed: exit $RC or wrong IMAGES"; sed 's/^/       /' "$LOG" "$STUB/IMAGES" 2>/dev/null
fi
SIGNER="--certificate-identity https://github.com/AdminCave/AdminHelper/.github/workflows/docker.yml@refs/tags/v1.2.3 --certificate-oidc-issuer https://token.actions.githubusercontent.com"
if [ "$(grep -cxF -- "verify $SIGNER ghcr.io/admincave/adminhelper/server@sha256:$(hex 1)" "$STUB/cosign.log")" -eq 1 ] \
   && [ "$(grep -c -- "@refs/tags/v1.2.3 " "$STUB/cosign.log")" -eq 5 ]; then
  ok "cosign verifies each digest against docker.yml of this tag"
else
  bad "cosign was not called with the signer of v1.2.3 on the digest"; sed 's/^/       /' "$STUB/cosign.log"
fi
if [ "$(stat -c %a "$STUB/IMAGES")" = 644 ]; then ok "IMAGES is 0644 (mktemp would leave 0600)"; else bad "IMAGES mode $(stat -c %a "$STUB/IMAGES")"; fi

# ── 2: one image missing on ghcr ─────────────────────────────────────────────
setup missing; rm "$STUB/digest-frps"
run v1.2.3 "$STUB/IMAGES"
red "image missing -> exit 1" "frps:1.2.3 not found on ghcr"

# ── 3: one image without a valid signature ──────────────────────────────────
setup unsigned; touch "$STUB/unsigned-monitoring"
run v1.2.3 "$STUB/IMAGES"
red "unsigned image -> exit 1" "monitoring:1.2.3 has no valid signature"

# ── 4: a malformed digest is refused, never written ─────────────────────────
setup malformed; echo "sha256:XYZ" > "$STUB/digest-gateway"
run v1.2.3 "$STUB/IMAGES"
red "malformed digest -> exit 1" "gateway:1.2.3 resolved to a malformed digest"

# ── 5: signature lands late (docker.yml still signing) → polls, then pins ──
setup late; echo 2 > "$STUB/late-ca-issuer"
run v1.2.3 "$STUB/IMAGES"
if [ "$RC" -eq 0 ] && grep -qx "CA_ISSUER_IMAGE=ghcr.io/admincave/adminhelper/ca-issuer:1.2.3@sha256:$(hex 4)" "$STUB/IMAGES"; then
  ok "late signature -> polled, then pinned"
else
  bad "late signature: exit $RC"; sed 's/^/       /' "$LOG"
fi
# ...but only within the budget: three late calls with three tries is red.
setup toolate; echo 3 > "$STUB/late-ca-issuer"
run v1.2.3 "$STUB/IMAGES"
red "signature later than the budget -> exit 1" "ca-issuer:1.2.3 has no valid signature"

# ── 6: argument handling ────────────────────────────────────────────────────
setup usage
for args in "" "1.2.3 $STUB/IMAGES" "v1.2 $STUB/IMAGES" "v1.2.3-rc1 $STUB/IMAGES" "v1.².3 $STUB/IMAGES" "v1.2.3"; do
  # shellcheck disable=SC2086 # word-splitting the case is the point
  run $args
  if [ "$RC" -eq 2 ] && grep -q "usage:" "$LOG" && [ ! -e "$STUB/IMAGES" ]; then
    ok "usage: '${args}' -> exit 2"
  else
    bad "usage: '${args}' -> exit $RC"
  fi
done

echo ""
echo "image_pins_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
