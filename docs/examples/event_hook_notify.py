# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

# Hook example (type: event): notification on connection changes
#
# Selectable events: connection.created, connection.updated, connection.deleted
#
# Context variables:
#   event_type  str   – e.g. "connection.created"
#   event_data  dict  – the affected connection
#
# Example payload for a chat notification (e.g. Slack, Teams, Mattermost):
#
# Available HTTP helpers: http_get(url, headers=None, timeout=10)
#                         http_post(url, json=None, headers=None, timeout=10)
# Return value: {"status": int, "body": str, "json": Any|None}

WEBHOOK_URL = "https://hooks.example.com/services/YOUR/SLACK/WEBHOOK"

name = event_data.get("name", "?")
kind = event_data.get("kind", "?")
host = event_data.get("host") or event_data.get("url") or "?"

action_labels = {
    "connection.created": "neu angelegt",
    "connection.updated": "geändert",
    "connection.deleted": "gelöscht",
}
action = action_labels.get(event_type, event_type)

msg = f"[AdminHelper] Verbindung {action}: *{name}* ({kind}, `{host}`)"

try:
    r = http_post(WEBHOOK_URL, json={"text": msg}, timeout=5)
    if r["status"] >= 400:
        raise ValueError(f"HTTP-Fehler {r['status']}: {r['body'][:200]}")
    result["notified"] = True
    log(f"Benachrichtigung gesendet: {msg}")
except Exception as e:
    result["notified"] = False
    result["error"] = str(e)
    log(f"Fehler beim Senden: {e}")
