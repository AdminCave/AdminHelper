# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""AdminHelper itself from its compose project (R-1235).

The services, ports and paths are those of AdminHelper's docker-compose.yml. db-init runs
once per `up` and then stays exited, so it has no container check; the frps container is
the frps module's (it finds AdminHelper's frps image too). The monitoring service
answers GET /health (port 8080), the CA issuer GET /healthz (port 8090), both without
touching the database; GET /health/detail of the monitoring service carries the scheduler's
lag and the failed alert mails of the last day. The gateway's TLS leaf is the one on 443 (nginx.conf); the issuer
keeps the root and the intermediates in its PKI directory (/app/data/pki: root.crt,
<scope>.crt) and the frps leaf in CA_FRPS_CERT_DIR (/app/frps-certs/frps.crt). The agent
reads these files through the container's mounts and opens nothing but the named file.
pg-backup is the optional backup service of the compose file: without it the backup check
does not bind. VictoriaMetrics keeps its data in /victoria-metrics-data
(-storageDataPath).
"""

_CONTAINER_RULES = [
    {"field": "state", "op": "ne", "value": "running", "level": "critical"},
    {"field": "health", "op": "eq", "value": "unhealthy", "level": "critical"},
]

# pg-backup writes once a day: two hours of slack, then a second day.
_DAY_AND_TWO_HOURS = 26 * 3600
_TWO_DAYS_AND_TWO_HOURS = 50 * 3600


def _container(key: str, name: str, service: str) -> dict:
    return {
        "key": key,
        "name": name,
        "sensor": "container",
        "target": {"kind": "container", "service": service},
        "interval": 300,
        "fields": ["state", "health", "restarts"],
        "rules": _CONTAINER_RULES,
    }


def _health(key: str, name: str, service: str, port: int, path: str) -> dict:
    return {
        "key": key,
        "name": name,
        "sensor": "http",
        "target": {"kind": "container", "service": service, "port_hint": port, "scheme": "http"},
        "params": {"path": path},
        "interval": 300,
        "fields": ["status_code", "duration_ms", "data.status"],
        "rules": [
            {"field": "status_code", "op": "ne", "value": 200, "level": "critical"},
            {"field": "data.status", "op": "ne", "value": "ok", "level": "critical"},
        ],
    }


def _ca_cert(key: str, name: str, path: str, warn_days: int, crit_days: int) -> dict:
    return {
        "key": key,
        "name": name,
        "sensor": "certfile",
        "target": {"kind": "container", "service": "ca-issuer"},
        "params": {"path": path},
        "interval": 86400,
        "fields": ["days_left", "not_after", "issuer"],
        "rules": [
            {"field": "days_left", "op": "lt", "value": warn_days, "level": "warning"},
            {"field": "days_left", "op": "lt", "value": crit_days, "level": "critical"},
        ],
    }


MODULE = {
    "id": "adminhelper",
    "name": "AdminHelper",
    "version": 1,
    "description": (
        "AdminHelper's own compose project: its containers, the health of monitoring and "
        "CA issuer, the certificates of gateway, frps and CA, the age of the database "
        "backups and the disk of VictoriaMetrics."
    ),
    "detect": {"container_images": ["ghcr.io/admincave/adminhelper"]},
    "instance": "compose_project",
    "checks": [
        _container("server", "Server container", "server"),
        _container("scheduler", "Scheduler container", "scheduler"),
        _container("gateway", "Gateway container", "gateway"),
        _container("ca_issuer", "CA issuer container", "ca-issuer"),
        _container("monitoring", "Monitoring container", "monitoring"),
        _container("postgres", "Postgres container", "postgres"),
        _container("redis", "Redis container", "redis"),
        _container("victoria", "VictoriaMetrics container", "victoria"),
        _health("monitoring_health", "Monitoring health", "monitoring", 8080, "/health"),
        _health("ca_issuer_health", "CA issuer health", "ca-issuer", 8090, "/healthz"),
        {
            # Numbers only (R-1235); neither the gateway nor the server's proxy forwards the
            # path. The scheduler runs each interval within it: ten minutes past is late.
            "key": "monitoring_scheduler",
            "name": "Monitoring scheduler and alert mail",
            "sensor": "http",
            "target": {
                "kind": "container",
                "service": "monitoring",
                "port_hint": 8080,
                "scheme": "http",
            },
            "params": {"path": "/health/detail"},
            "interval": 300,
            "fields": [
                "status_code",
                "data.scheduler_lag_s",
                "data.mail_failed_24h",
                "data.mail_last_ok_age_s",
            ],
            "rules": [
                {"field": "status_code", "op": "ne", "value": 200, "level": "critical"},
                {"field": "data.scheduler_lag_s", "op": "gt", "value": 600, "level": "warning"},
                {"field": "data.scheduler_lag_s", "op": "gt", "value": 1800, "level": "critical"},
                {"field": "data.mail_failed_24h", "op": "gt", "value": 0, "level": "warning"},
            ],
        },
        {
            # The issuer re-mints the leaf on boot past half its 365 days (pki.py
            # LEAF_DAYS_GATEWAY): a warning means the stack has not restarted since.
            "key": "gateway_certificate",
            "name": "Gateway certificate",
            "sensor": "tls",
            "target": {"kind": "container", "service": "gateway", "port_hint": 443},
            "interval": 3600,
            "fields": ["days_left", "not_after", "issuer"],
            "rules": [
                {"field": "days_left", "op": "lt", "value": 30, "level": "warning"},
                {"field": "days_left", "op": "lt", "value": 7, "level": "critical"},
            ],
        },
        _ca_cert("frps_certificate", "frps certificate", "/app/frps-certs/frps.crt", 30, 7),
        # The issuer's own warnings: a year for the root (pki.py ROOT_WARN_DAYS), half a
        # year for an intermediate (EXPIRY_WARN_DAYS).
        _ca_cert("ca_root", "CA root", "/app/data/pki/root.crt", 365, 90),
        _ca_cert("ca_tunnel", "CA intermediate tunnel", "/app/data/pki/tunnel.crt", 180, 30),
        _ca_cert("ca_access", "CA intermediate access", "/app/data/pki/access.crt", 180, 30),
        _ca_cert("ca_internal", "CA intermediate internal", "/app/data/pki/internal.crt", 180, 30),
        {
            "key": "backup",
            "name": "Database backup",
            "sensor": "file_age",
            "target": {"kind": "container", "service": "pg-backup"},
            "params": {"newest_in": "/backups"},
            "interval": 3600,
            "fields": ["exists", "age_s", "size_bytes"],
            "rules": [
                {"field": "exists", "op": "eq", "value": False, "level": "warning"},
                {"field": "age_s", "op": "gt", "value": _DAY_AND_TWO_HOURS, "level": "warning"},
                {
                    "field": "age_s",
                    "op": "gt",
                    "value": _TWO_DAYS_AND_TWO_HOURS,
                    "level": "critical",
                },
            ],
        },
        {
            "key": "metrics_disk",
            "name": "VictoriaMetrics disk",
            "sensor": "fs",
            "target": {"kind": "container", "service": "victoria"},
            "params": {"path": "/victoria-metrics-data"},
            "interval": 900,
            "fields": ["used_pct", "free_bytes", "inodes_used_pct"],
            "rules": [
                {"field": "used_pct", "op": "ge", "value": 80, "level": "warning"},
                {"field": "used_pct", "op": "ge", "value": 90, "level": "critical"},
                {"field": "inodes_used_pct", "op": "ge", "value": 90, "level": "warning"},
            ],
        },
    ],
    "card": [
        {"check_key": "monitoring_health", "field": "status_code", "label": "Monitoring"},
        {"check_key": "ca_issuer_health", "field": "status_code", "label": "CA issuer"},
        {"check_key": "gateway_certificate", "field": "days_left", "label": "Gateway cert days"},
        {"check_key": "ca_root", "field": "days_left", "label": "CA root days"},
        {"check_key": "backup", "field": "age_s", "label": "Newest backup s"},
        {"check_key": "metrics_disk", "field": "used_pct", "label": "Metrics disk %"},
    ],
}
