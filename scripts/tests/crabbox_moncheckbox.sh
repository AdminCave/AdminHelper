#!/usr/bin/env bash
#
# crabbox_moncheckbox.sh — S5 monitoring-check client + alert sink. Two modes:
#   start   run a mailhog SMTP catcher (SMTP :1025, HTTP :8025) — the alert sink.
#           The box is also the reachable ping target for the monitoring "ok" check.
#   assert  verify mailhog caught the critical-alert email (closes the loop).
#
# Called by scripts/tests/crabbox_multibox.sh --moncheck via `crabbox run`.
#   crabbox_moncheckbox.sh <start|assert>
set -uo pipefail
MODE="${1:?usage: crabbox_moncheckbox.sh <start|assert>}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT" || exit 1

if [ "$MODE" = start ]; then
  echo "[moncheckbox] hydrate (agent profile: docker) + run mailhog"
  AH_BOOTSTRAP_PROFILE=agent bash scripts/tests/crabbox_bootstrap.sh || { echo "[moncheckbox] bootstrap failed"; exit 1; }
  sudo docker rm -f mailhog >/dev/null 2>&1 || true
  # mailhog is a static Go binary (runs on the baseline kvm64 CPU); SMTP 1025, UI/API 8025.
  sudo docker run -d --name mailhog -p 1025:1025 -p 8025:8025 mailhog/mailhog >/dev/null 2>&1 \
    || { echo "MC_MAILHOG_FAIL"; sudo docker logs mailhog 2>&1 | tail -10; exit 1; }
  # Poll mailhog's HTTP UI instead of a fixed sleep — proves it actually listens, not
  # just that the container exists (docker ps shows that instantly, before it's up) (6.137).
  mh_ok=0
  for _ in $(seq 1 15); do curl -sf http://127.0.0.1:8025/ >/dev/null 2>&1 && { mh_ok=1; break; }; sleep 1; done
  if [ "$mh_ok" = 1 ]; then echo "MC_MAILHOG_UP"; else echo "MC_MAILHOG_FAIL"; sudo docker logs mailhog 2>&1 | tail -10; exit 1; fi

elif [ "$MODE" = assert ]; then
  echo "[moncheckbox] query mailhog for the caught alert email"
  COUNT="$(curl -s http://localhost:8025/api/v2/messages 2>/dev/null | python3 -c 'import sys,json; print(json.load(sys.stdin).get("total",0))' 2>/dev/null || echo 0)"
  echo "MC_MAIL_COUNT=$COUNT"
  if [ "${COUNT:-0}" -ge 1 ] 2>/dev/null; then echo "MC_ALERT_RECEIVED"; else echo "MC_NO_ALERT"; exit 1; fi

else
  echo "unknown mode: $MODE (use start|assert)"; exit 2
fi
