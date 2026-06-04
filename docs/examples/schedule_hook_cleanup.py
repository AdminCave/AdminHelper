# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

# Hook example (type: schedule): daily cleanup of duplicates
#
# Recommended interval: 24h
#
# Context variables:
#   triggered_at  str        – ISO timestamp of this run
#   last_run      str|None   – previous run (ISO) or None on the first run
#
# The script removes duplicate connections based on (kind, host, port).
# Two connections count as duplicates when these three fields match;
# the first variant found is kept.

connections = load_connections()
seen = set()
unique = []

for conn in connections:
    key = (
        str(conn.get("kind", "")).lower(),
        str(conn.get("host", "")).strip().lower(),
        conn.get("port"),
    )
    if key not in seen:
        seen.add(key)
        unique.append(conn)

removed = len(connections) - len(unique)

if removed > 0:
    save_connections(unique)
    log(f"Bereinigt: {removed} Duplikat(e) entfernt")
else:
    log("Keine Duplikate gefunden")

result["removed_duplicates"] = removed
result["total_after"] = len(unique)
result["triggered_at"] = triggered_at
result["previous_run"] = last_run
