#!/usr/bin/env bash
#
# crabbox_moncheckbox.sh — S5 monitoring-check client + alert sink. Two modes:
#   start <ip>  run a mailpit SMTP catcher (SMTP :1025, HTTP :8025) — the alert sink.
#           The box is also the reachable ping target for the monitoring "ok" check.
#   assert  verify the sink caught the critical-alert email (closes the loop).
#
# The sink speaks STARTTLS with a self-signed cert carrying an IP SAN for <ip>,
# and prints it as MC_CA_B64 so the server box can trust it. That is NOT
# decoration: the alerter mandates STARTTLS on every non-465 port and verifies
# cert + hostname (audit 3.24), so a plaintext catcher like mailhog can never
# receive an alert — the closed loop silently proved nothing until v0.44.0.
#
# Called by scripts/tests/crabbox_multibox.sh --moncheck via `crabbox run`.
#   crabbox_moncheckbox.sh <start <ip>|assert>
set -uo pipefail
MODE="${1:?usage: crabbox_moncheckbox.sh <start <ip>|assert>}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT" || exit 1

if [ "$MODE" = start ]; then
  MC_IP="${2:?usage: crabbox_moncheckbox.sh start <ip>}"
  echo "[moncheckbox] hydrate (agent profile: docker) + run mailpit (STARTTLS)"
  AH_BOOTSTRAP_PROFILE=agent bash scripts/tests/crabbox_bootstrap.sh || { echo "[moncheckbox] bootstrap failed"; exit 1; }

  # Self-signed cert with an IP SAN for this box: the alerter verifies cert AND
  # hostname, and smtp_host is the box IP — a CN-only or hostname-SAN cert would
  # fail verification. CA:TRUE so the same PEM works as the trust anchor.
  CERTDIR=/tmp/mc-tls; sudo rm -rf "$CERTDIR"; mkdir -p "$CERTDIR"
  openssl req -x509 -newkey rsa:2048 -nodes -days 2 \
    -keyout "$CERTDIR/key.pem" -out "$CERTDIR/cert.pem" \
    -subj "/CN=$MC_IP" \
    -addext "subjectAltName=IP:$MC_IP" \
    -addext "basicConstraints=critical,CA:TRUE" >/dev/null 2>&1 \
    || { echo "MC_MAILPIT_FAIL (openssl)"; exit 1; }
  chmod 644 "$CERTDIR/key.pem" "$CERTDIR/cert.pem"

  sudo docker rm -f mailhog mailpit >/dev/null 2>&1 || true
  # mailpit (mailhog's maintained successor) is the sink because it speaks
  # STARTTLS; REQUIRE_STARTTLS makes the test fail loudly if the alerter ever
  # regresses to plaintext instead of silently passing.
  sudo docker run -d --name mailpit -p 1025:1025 -p 8025:8025 \
    -v "$CERTDIR:/tls:ro" \
    -e MP_SMTP_TLS_CERT=/tls/cert.pem -e MP_SMTP_TLS_KEY=/tls/key.pem \
    -e MP_SMTP_REQUIRE_STARTTLS=true \
    axllent/mailpit >/dev/null 2>&1 \
    || { echo "MC_MAILPIT_FAIL"; sudo docker logs mailpit 2>&1 | tail -10; exit 1; }
  # Poll the HTTP UI instead of a fixed sleep — proves it actually listens, not
  # just that the container exists (docker ps shows that instantly) (6.137).
  mh_ok=0
  for _ in $(seq 1 30); do curl -sf http://127.0.0.1:8025/ >/dev/null 2>&1 && { mh_ok=1; break; }; sleep 1; done
  [ "$mh_ok" = 1 ] || { echo "MC_MAILPIT_FAIL"; sudo docker logs mailpit 2>&1 | tail -10; exit 1; }
  echo "MC_CA_B64=$(base64 -w0 < "$CERTDIR/cert.pem")"
  echo "MC_MAILHOG_UP"  # marker name kept — the orchestrator greps for it

elif [ "$MODE" = assert ]; then
  echo "[moncheckbox] query the sink for the caught alert email"
  # Grep the raw listing instead of a typed field: the check name is unique
  # ("[AdminHelper Monitor] CRITICAL: mc-ping-crit"), so a hit is unambiguous,
  # and the assertion survives sink-API changes. A one-off flap of the unrelated
  # mc-ping-ok check still cannot pass as this alert (6.134).
  BODY="$(curl -s 'http://localhost:8025/api/v1/messages?limit=200' 2>/dev/null)"
  if printf '%s' "$BODY" | grep -q 'mc-ping-crit'; then
    MATCH=1
  else
    MATCH=0
    echo "[moncheckbox] sink listing (first 400 chars): $(printf '%s' "$BODY" | head -c 400)"
    sudo docker logs mailpit 2>&1 | tail -15
  fi
  echo "MC_ALERT_MATCH=$MATCH"
  if [ "$MATCH" = 1 ]; then echo "MC_ALERT_RECEIVED"; else echo "MC_NO_ALERT"; exit 1; fi

else
  echo "unknown mode: $MODE (use start|assert)"; exit 2
fi
