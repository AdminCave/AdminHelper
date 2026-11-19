# kern-monitoring-51 — Monitoring-Nachlese: Dienstnamen unter Windows, agent_ping nach Stillstand, Cleanup-Entwarnungen, Lastschonung

Roadmap: R-0436, R-1607, R-1622, R-1616 (R-1630 wanderte wegen Überschneidung mit `feature/kern-provision-2` nach kern-monitoring-52).

## Problem

- **R-0436:** `service_process` im Modus `list` vergleicht Dienstnamen wörtlich. Unter Windows heißt der Dienst `W32Time`; ein eingetragenes `w32time` findet ihn nicht und steht als „nicht gefunden“. Windows selbst vergleicht Dienstnamen ohne Groß-/Kleinschreibung: „The service control manager database preserves the case of the characters, but service name comparisons are always case insensitive.“ (https://learn.microsoft.com/en-us/windows/win32/api/winsvc/nf-winsvc-createservicew, `lpServiceName`).
- **R-1607:** `agent_ping` zählt nach einem Stillstand des Monitoring-Dienstes die Stillstandszeit mit. Der Zeitstempel kommt beim Start aus der DB (`hydrate_agent_liveness`), und der erste Lauf meldet einen Agent kritisch, dessen Push knapp danach eintrifft. Während des Stillstands konnte kein Push ankommen; das Alter darf daher höchstens ab dem Start des Dienstes zählen.
- **R-1622:** `cleanup_server` schickt die Entwarnungen der gelöschten Checks synchron im Request (`send_all_clears`). Bei vielen offenen Alarmen läuft der Aufruf über das 5-s-Timeout des Servers, der dann „Cleanup fehlgeschlagen“ loggt, obwohl die Löschung committet ist.
- **R-1616:** Der Push-Pfad nimmt ein `load_shed.since` in der Zukunft hin (`routers/agent.py`, `now - shed_since` negativ): die Checks gelten dann beliebig lange als „gehalten“ statt nach 15 min als nicht gemessen.

## Ziel & Nicht-Ziele

- Windows-Hosts (Host-Fakt `os` = `windows` im Bericht): `list` findet Namen ohne Rücksicht auf Groß-/Kleinschreibung. Linux und FreeBSD bleiben wörtlich (systemd-Units und rc.d-Skripte unterscheiden sie). Nicht-Ziel: das Agent-seitige Kleinschreiben.
- `agent_ping`: ein Zeitstempel aus der DB (ohne monotonen Partner) zählt höchstens ab Prozessstart. Ein toter Agent ist `stale_minutes` nach dem Start kritisch.
- Cleanup: Entwarnungen gehen nach der Antwort (FastAPI `BackgroundTasks`), Vertrag und Antwort unverändert.
- `since` in der Zukunft gilt als jetzt.

## Betroffene Komponenten & Dateien

`apps/monitoring/app/checkers/agent.py` (`ServiceProcessChecker._evaluate_list`, `AgentPingChecker.run`, `hydrate_agent_liveness`), `apps/monitoring/app/server_cleanup.py`, `apps/monitoring/app/routers/admin.py`, `apps/monitoring/app/routers/agent.py`; Tests unter `apps/monitoring/tests/`.

## Datenmodell / API / Migrationen

Keine Migration, kein Vertragswechsel. Die Cleanup-Route bekommt `BackgroundTasks` als Abhängigkeit, Schema und Docstring bleiben (OpenAPI-Snapshot unverändert).

## Trade-offs & Alternativen

- R-0436: Groß-/Kleinschreibung immer ignorieren wäre einfacher, verwischt aber unter Linux zwei verschiedene Units. Empfehlung: nur Windows, erkannt am Host-Fakt des Berichts; fehlt er (Agent vor R-0421), bleibt der wörtliche Vergleich.
- R-1607: Alternative „erster Lauf nach dem Start unknown“ ließe einen toten Agent eine Periode lang ok. Die Kappung auf die Laufzeit ist ehrlich in beide Richtungen.

## Risiken & Rollback

Je Task ein Commit, einzeln zurücknehmbar. R-1607 verschiebt den ersten kritischen Befund eines toten Agents nach einem Neustart auf `stale_minutes` nach dem Start; die Host-Down-Hemmung greift entsprechend später.

## Doku-Impact

`docs/admin/monitoring.html` DE+EN: Modus `list` (Windows ohne Groß-/Kleinschreibung) und `agent_ping` (nach einem Neustart des Monitoring-Dienstes zählt das Alter ab dem Start). Changelog `changelog.d/kern-monitoring-51.md`.

## Offene Fragen

Keine.
