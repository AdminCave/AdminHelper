from __future__ import annotations

import logging
import time

import httpx

from app.core.config import VICTORIA_METRICS_URL

logger = logging.getLogger("monitor.victoria")


class VictoriaClient:
    """Client fuer VictoriaMetrics HTTP-API."""

    def __init__(self, base_url: str = VICTORIA_METRICS_URL):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=10)

    def write(self, metrics: list[str]) -> None:
        """Metriken im InfluxDB Line Protocol Format schreiben."""
        if not metrics:
            return
        body = "\n".join(metrics)
        try:
            resp = self._client.post(f"{self.base_url}/write", content=body)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("VictoriaMetrics write fehlgeschlagen: %s", exc)

    def write_check_result(
        self,
        check_id: str,
        check_type: str,
        server_id: str | None,
        name: str,
        status: str,
        duration_ms: int,
        extra_metrics: dict | None = None,
    ) -> None:
        """Schreibt Check-Ergebnis als Metriken."""
        status_map = {"ok": 0, "warning": 1, "critical": 2, "unknown": 3}
        status_val = status_map.get(status, 3)
        ts = int(time.time())

        tags = f'check_id="{check_id}",check_type="{check_type}",name="{name}"'
        if server_id:
            tags += f',server_id="{server_id}"'

        lines = [
            f"monitor_check_status{{{tags}}} {status_val} {ts}",
            f"monitor_check_duration_ms{{{tags}}} {duration_ms} {ts}",
        ]

        if extra_metrics:
            for key, value in extra_metrics.items():
                if isinstance(value, (int, float)):
                    lines.append(f"monitor_{key}{{{tags}}} {value} {ts}")

        self.write(lines)

    def query_range(self, query: str, start: str, end: str, step: str) -> dict:
        """PromQL Range-Query fuer Charts."""
        try:
            resp = self._client.get(
                f"{self.base_url}/api/v1/query_range",
                params={"query": query, "start": start, "end": end, "step": step},
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            logger.warning("VictoriaMetrics query_range fehlgeschlagen: %s", exc)
            return {"status": "error", "data": {"result": []}}

    def query_instant(self, query: str) -> dict:
        """PromQL Instant-Query fuer aktuelle Werte."""
        try:
            resp = self._client.get(
                f"{self.base_url}/api/v1/query",
                params={"query": query},
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            logger.warning("VictoriaMetrics query fehlgeschlagen: %s", exc)
            return {"status": "error", "data": {"result": []}}


# Singleton-Instanz
victoria = VictoriaClient()
