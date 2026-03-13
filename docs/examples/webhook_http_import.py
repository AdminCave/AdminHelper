# Hook-Beispiel (Typ: webhook): Verbindungen per HTTP-API importieren
# Trigger: POST /api/hooks/trigger/<TOKEN>
#
# Dieses Script ruft eine externe API ab und fügt alle Hosts,
# die noch nicht als Verbindung existieren, automatisch hinzu.
#
# Erwarteter JSON-Body (optional):
# {
#   "api_url": "https://cmdb.example.com/api/servers",  <- überschreibt den Default
#   "kind": "ssh",                                       <- Verbindungstyp (ssh/rdp/web)
#   "tags": ["auto-import"]                              <- zusätzliche Tags
# }
#
# Die externe API muss ein JSON-Array zurückliefern mit Objekten, die mindestens
# "hostname" (str) und "ip" (str) enthalten. Optionale Felder: "tags" (list[str]).
#
# Beispiel-Response der externen API:
# [
#   {"hostname": "web-01", "ip": "10.0.0.1", "tags": ["prod", "web"]},
#   {"hostname": "db-01",  "ip": "10.0.0.2", "tags": ["prod", "db"]}
# ]

import requests

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

r = requests.get(api_url, timeout=10)
r.raise_for_status()

servers = r.json()
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
