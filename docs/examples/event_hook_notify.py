# Hook-Beispiel (Typ: event): Benachrichtigung bei Verbindungsänderungen
#
# Events auswählen: connection.created, connection.updated, connection.deleted
#
# Kontext-Variablen:
#   event_type  str   – z. B. "connection.created"
#   event_data  dict  – die betroffene Verbindung
#
# Beispiel-Payload für eine Chat-Benachrichtigung (z. B. Slack, Teams, Mattermost):

import requests

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

msg = f"[SRM] Verbindung {action}: *{name}* ({kind}, `{host}`)"

try:
    r = requests.post(WEBHOOK_URL, json={"text": msg}, timeout=5)
    r.raise_for_status()
    result["notified"] = True
    log(f"Benachrichtigung gesendet: {msg}")
except Exception as e:
    result["notified"] = False
    result["error"] = str(e)
    log(f"Fehler beim Senden: {e}")
