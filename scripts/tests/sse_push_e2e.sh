#!/usr/bin/env bash
#
# sse_push_e2e.sh — live E2E for the SSE push infrastructure: cross-instance
# Redis fan-out over real HTTP/SSE.
#
# This is the ONE path the server unit/integration tests cannot cover: that a
# notification raised on ONE worker reaches an SSE stream connected to ANOTHER
# worker. We boot TWO independent server processes (A:8081, B:8082) sharing one
# Postgres + Redis, then:
#
#   1. login against A                      -> JWT
#   2. subscribe (scope=all) against A
#   3. open the SSE stream against A         (registers on instance A only)
#   4. inject an event against B             (POST /api/internal/events)
#   5. expect A to receive the notification  (A <- Redis <- B = cross-instance)
#
# Two SEPARATE processes (not `uvicorn --workers 2`) make cross-instance
# DETERMINISTIC: Redis is the only path between them. Needs docker, plus the
# server venv (default /tmp/ah-venv, override with VENV=...). SKIPs cleanly when
# docker is unavailable. Run: bash scripts/tests/sse_push_e2e.sh
set -euo pipefail

if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
  echo "SKIP: docker not available"
  exit 0
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SERVER="$ROOT/apps/server"
VENV="${VENV:-/tmp/ah-venv}"
PY="$VENV/bin"
if [ ! -x "$PY/uvicorn" ]; then
  echo "SKIP: server venv not found at $VENV (set VENV=...)"
  exit 0
fi

export DATABASE_URL="postgresql+psycopg://adminhelper:adminhelper@localhost:5433/adminhelper"
export REDIS_URL="redis://localhost:6380/0"
export MONITOR_API_KEY="e2e-internal-key"
export SECRET_KEY="e2e-secret-key-not-for-production-32bytes"
export ADMIN_PASSWORD="e2e-admin-pw"
export MTLS_ENFORCE="false"
DATA_DIR="$(mktemp -d)"; export DATA_DIR  # separate assign: don't mask mktemp's exit (SC2155)
export WEB_CONCURRENCY="1"

PID_A=""; PID_B=""
cleanup() {
  [ -n "$PID_A" ] && kill "$PID_A" 2>/dev/null || true
  [ -n "$PID_B" ] && kill "$PID_B" 2>/dev/null || true
  docker rm -f ah-sse-e2e-pg ah-sse-e2e-redis >/dev/null 2>&1 || true
  rm -rf "$DATA_DIR" 2>/dev/null || true
}
trap cleanup EXIT

docker rm -f ah-sse-e2e-pg ah-sse-e2e-redis >/dev/null 2>&1 || true
docker run -d --name ah-sse-e2e-pg -e POSTGRES_USER=adminhelper -e POSTGRES_PASSWORD=adminhelper \
  -e POSTGRES_DB=adminhelper -p 127.0.0.1:5433:5432 postgres:17-alpine >/dev/null
docker run -d --name ah-sse-e2e-redis -p 127.0.0.1:6380:6379 redis:7-alpine >/dev/null
echo "[stack] waiting for postgres..."
for _ in $(seq 1 30); do docker exec ah-sse-e2e-pg pg_isready -U adminhelper >/dev/null 2>&1 && break; sleep 1; done

cd "$SERVER"
echo "[stack] alembic upgrade head"
"$PY/alembic" upgrade head >/dev/null

# Instance A first (it bootstraps the admin), then B, to avoid a startup race.
"$PY/uvicorn" app.main:app --host 127.0.0.1 --port 8081 >/tmp/sse-e2e-a.log 2>&1 & PID_A=$!
for _ in $(seq 1 40); do curl -sf http://127.0.0.1:8081/api/docs >/dev/null 2>&1 && break; sleep 0.5; done
"$PY/uvicorn" app.main:app --host 127.0.0.1 --port 8082 >/tmp/sse-e2e-b.log 2>&1 & PID_B=$!
for _ in $(seq 1 40); do curl -sf http://127.0.0.1:8082/api/docs >/dev/null 2>&1 && break; sleep 0.5; done
echo "[stack] both instances up"

"$PY/python" - <<'PYEOF'
import asyncio, os, sys
import httpx

A, B = "http://127.0.0.1:8081", "http://127.0.0.1:8082"
KEY, PW = os.environ["MONITOR_API_KEY"], os.environ["ADMIN_PASSWORD"]


async def main() -> int:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(f"{A}/api/auth/login", json={"username": "admin", "password": PW})
        r.raise_for_status()
        token = r.json()["access_token"]
        auth = {"Authorization": f"Bearer {token}"}
        r = await c.put(f"{A}/api/users/me/notification-prefs", headers=auth, json={
            "email": None, "telegram_chat_id": None,
            "subscriptions": [{"scope_type": "all", "min_severity": "info",
                               "channel_email": False, "channel_telegram": False, "enabled": True}]})
        r.raise_for_status()
        print("[e2e] logged in + subscribed (scope=all)")

    got = asyncio.Event()

    async def reader():
        async with httpx.AsyncClient(timeout=None) as sc:
            async with sc.stream("GET", f"{A}/api/notifications/stream",
                                 headers={"Authorization": f"Bearer {token}",
                                          "Accept": "text/event-stream"}) as resp:
                print(f"[e2e] stream against A: HTTP {resp.status_code}")
                if resp.status_code != 200:
                    return
                async for line in resp.aiter_lines():
                    if line.startswith("event: notification"):
                        got.set(); return

    task = asyncio.create_task(reader())
    await asyncio.sleep(2.0)  # let the stream register + Redis subscription settle

    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(f"{B}/api/internal/events", headers={"X-Internal-Key": KEY},
                         json={"event_type": "monitoring.check.transition", "severity": "critical",
                               "category": "monitoring", "title": "E2E CPU critical"})
        r.raise_for_status()
        print(f"[e2e] event injected on B -> {r.json()}")

    try:
        await asyncio.wait_for(got.wait(), timeout=5)
        print("[e2e] PASS: A received the SSE notification after the event hit B (cross-instance fan-out)")
        rc = 0
    except asyncio.TimeoutError:
        print("[e2e] FAIL: no SSE frame on A within 5s")
        rc = 1
    task.cancel()
    return rc


sys.exit(asyncio.run(main()))
PYEOF
echo "[stack] done"
