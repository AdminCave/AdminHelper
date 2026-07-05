# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

# Hook example (type: webhook): create or update a connection
# Trigger: POST /api/hooks/trigger  with header  X-Hook-Token: <TOKEN>  (preferred)
#          or POST /api/hooks/trigger/<TOKEN>  (token in path — leaks into logs)
# Expected JSON body:
# {
#   "connection": {
#     "id": "optional-uuid",
#     "name": "Prod Web",
#     "kind": "web",
#     "url": "https://prod.example.com",
#     "tags": ["prod", "web"]
#   }
# }

connections = load_connections()
incoming = payload.get("connection")

if not isinstance(incoming, dict):
    raise ValueError("payload.connection muss ein Objekt sein")

name = str(incoming.get("name", "")).strip()
kind = str(incoming.get("kind", "")).strip().lower()

if not name:
    raise ValueError("connection.name fehlt")
if kind not in ("ssh", "rdp", "web"):
    raise ValueError("connection.kind muss ssh, rdp oder web sein")

host = str(incoming.get("host", "")).strip()
url = str(incoming.get("url", "")).strip()

if kind in ("ssh", "rdp") and not host:
    raise ValueError("connection.host fehlt")
if kind == "web" and not url:
    raise ValueError("connection.url fehlt")

raw_port = incoming.get("port")
port = None
if raw_port not in (None, ""):
    if not isinstance(raw_port, int):
        raise ValueError("connection.port muss eine Zahl sein")
    if raw_port < 1 or raw_port > 65535:
        raise ValueError("connection.port muss zwischen 1 und 65535 liegen")
    port = raw_port

raw_tags = incoming.get("tags", [])
if not isinstance(raw_tags, list):
    raw_tags = []

tags = []
for tag in raw_tags:
    t = str(tag).strip()
    if t and t not in tags:
        tags.append(t)

incoming_id = str(incoming.get("id", "")).strip()
lookup_name = name.lower()

found_index = None
for i, conn in enumerate(connections):
    conn_id = str(conn.get("id", "")).strip()
    conn_name = str(conn.get("name", "")).strip().lower()
    conn_kind = str(conn.get("kind", "")).strip().lower()

    if incoming_id and conn_id == incoming_id:
        found_index = i
        break

    if not incoming_id and conn_name == lookup_name and conn_kind == kind:
        found_index = i
        break

connection_id = incoming_id
if not connection_id:
    if found_index is not None:
        connection_id = str(connections[found_index].get("id", "")).strip()
    if not connection_id:
        connection_id = uuid4()

updated_connection = {
    "id": connection_id,
    "name": name,
    "kind": kind,
    "host": host,
    "port": port,
    "username": str(incoming.get("username", "")).strip(),
    "domain": str(incoming.get("domain", "")).strip(),
    "keyPath": str(incoming.get("keyPath", "")).strip(),
    "url": url,
    "notes": str(incoming.get("notes", "")).strip(),
    "tags": tags,
    "trustCert": bool(incoming.get("trustCert", False)),
    "lastUsed": incoming.get("lastUsed"),
}

mode = "created"
if found_index is None:
    connections.append(updated_connection)
else:
    connections[found_index] = updated_connection
    mode = "updated"

save_connections(connections)

result["mode"] = mode
result["connectionId"] = connection_id
result["name"] = name
result["kind"] = kind
result["totalConnections"] = len(connections)

log(f"{mode}: {name} ({kind})")
