# Hook-Beispiel (Typ: schedule): Tägliche Bereinigung von Duplikaten
#
# Empfohlenes Intervall: 24h
#
# Kontext-Variablen:
#   triggered_at  str        – ISO-Zeitstempel dieser Ausführung
#   last_run      str|None   – letzter Lauf (ISO) oder None beim ersten Lauf
#
# Das Script entfernt Verbindungs-Duplikate basierend auf (kind, host, port).
# Zwei Verbindungen gelten als Duplikat, wenn diese drei Felder übereinstimmen;
# die erste gefundene Variante bleibt erhalten.

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
