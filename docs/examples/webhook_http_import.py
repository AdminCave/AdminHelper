# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

# Hook example (type: webhook): import connections via HTTP API
# Trigger: POST /api/hooks/trigger  with header  X-Hook-Token: <TOKEN>  (preferred)
#          or POST /api/hooks/trigger/<TOKEN>  (token in path — leaks into logs)
#
# This script fetches an external API and automatically adds all hosts
# that do not yet exist as a connection.
#
# Expected JSON body (optional):
# {
#   "api_url": "https://cmdb.example.com/api/servers",  <- overrides the default
#   "kind": "ssh",                                       <- connection type (ssh/rdp/web)
#   "tags": ["auto-import"]                              <- additional tags
# }
#
# The external API must return a JSON array of objects that contain at least
# "hostname" (str) and "ip" (str). Optional fields: "tags" (list[str]).
#
# Example response from the external API:
# [
#   {"hostname": "web-01", "ip": "10.0.0.1", "tags": ["prod", "web"]},
#   {"hostname": "db-01",  "ip": "10.0.0.2", "tags": ["prod", "db"]}
# ]
#
# Available HTTP helpers: http_get(url, headers=None, timeout=10)
#                         http_post(url, json=None, headers=None, timeout=10)
# Return value: {"status": int, "body": str, "json": Any|None}
# Both helpers reject private/internal/metadata targets (SSRF guard) and do NOT
# follow redirects; the reflected body is capped at 1 MB.

DEFAULT_API_URL = "https://cmdb.example.com/api/servers"
DEFAULT_KIND = "ssh"
DEFAULT_PORT = {"ssh": 22, "rdp": 3389, "web": None}

api_url = str(payload.get("api_url", DEFAULT_API_URL)).strip()
kind = str(payload.get("kind", DEFAULT_KIND)).strip().lower()
extra_tags = payload.get("tags", [])

if kind not in ("ssh", "rdp", "web"):
    raise ValueError(f"kind muss ssh, rdp oder web sein, nicht '{kind}'")
if not isinstance(extra_tags, list):
    extra_tags = []

r = http_get(api_url, timeout=10)
if r["status"] >= 400:
    raise ValueError(f"HTTP-Fehler {r['status']}: {r['body'][:200]}")

servers = r["json"]
if not isinstance(servers, list):
    raise ValueError("Externe API muss ein JSON-Array zurückliefern")

connections = load_connections()
existing_hosts = {c.get("host") for c in connections}

added = 0
skipped = 0

for srv in servers:
    hostname = str(srv.get("hostname", "")).strip()
    ip = str(srv.get("ip", "")).strip()

    if not hostname or not ip:
        log(f"Übersprungen: fehlende hostname oder ip in {srv}")
        skipped += 1
        continue

    if ip in existing_hosts:
        log(f"Übersprungen (existiert bereits): {hostname} ({ip})")
        skipped += 1
        continue

    srv_tags = [t for t in srv.get("tags", []) if isinstance(t, str)]
    all_tags = list({*srv_tags, *extra_tags})

    new_conn = {
        "id": uuid4(),
        "name": hostname,
        "host": ip,
        "kind": kind,
        "port": DEFAULT_PORT.get(kind),
        "username": "",
        "domain": "",
        "keyPath": "",
        "url": "",
        "notes": f"Auto-importiert von {api_url}",
        "tags": all_tags,
        "trustCert": False,
        "lastUsed": None,
    }

    connections.append(new_conn)
    existing_hosts.add(ip)
    added += 1
    log(f"Hinzugefügt: {hostname} ({ip})")

save_connections(connections)

result["added"] = added
result["skipped"] = skipped
result["total"] = len(connections)
result["source"] = api_url
