# Sent-State-Tracking für den Monitoring-Alerter — Task-Ledger
Status: aktiv · Branch: feature/alert-sent-state · Commit-Granularität: pro Task · Review: pro Task (feature-review) · Modell: Opus
Spec: docs/features/alert-sent-state.md
Basis: feature/monitoring-overhaul (stacked auf PR #4 — NICHT von main forken: `git switch -c feature/alert-sent-state feature/monitoring-overhaul`; nach Merge von PR #4 auf main rebasen, PR-Base entsprechend)
Fast-Suite: lokal · Warm-Profil: desktop
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Hinweis: Nur apps/monitoring wird berührt (Server-Contract unverändert — new_status
im Hub-Payload existiert seit T36 des Overhauls). Kein multibox; schwere Verifikation
am Abschluss via `run.sh integration` auf der Desktop-Warm-Box (Monitoring-Pipeline).

## Phase 1 — Datenmodell

### T1 — notified_status: Spalte + Migration mit Backfill  [ ]
Komponente: apps/monitoring · Dateien: app/models.py, alembic/versions/<neu>_notified_status.py
Änderung: `MonitorState.notified_status` (String, nullable) — der zuletzt real gemeldete Status. Alembic-Revision nach Head `b7d9f1a3c5e7`; Upgrade backfillt `notified_status = status` (Bestand gilt als gemeldet → kein Nachmelde-Sturm beim Deploy), Downgrade droppt die Spalte. `to_dict()` gibt `notifiedStatus` additiv mit aus.
Verify: `cd apps/monitoring && .venv/bin/python -m pytest -q tests/ -k "alembic or smoke"` (Parity-Smoke grün) `&& .venv/bin/python -m pytest -q tests/`
Doku: keine (intern; Doku in T7)

## Phase 2 — Kernlogik

### T2 — Reine Entscheidungsfunktion resolve_notification  [ ]
Komponente: apps/monitoring · Dateien: app/alerter.py, tests/test_alerter_sent_state.py (neu, SPDX-Header)
Änderung: Pure Funktion (z. B. `resolve_notification(notified_status, new_status) -> "notify" | "silent_ack" | "skip"`): `new == notified` → skip; `new == "unknown"` → skip (notified unverändert); `new == "ok"` mit `notified ∉ {warning, critical}` → silent_ack (notified still auf ok, keine Meldung — deckt pending/NULL-Erststart und unknown-Flapping ab); sonst notify. Vollständige Matrix-Tests (notified ∈ {None, pending, ok, warning, critical, unknown} × new ∈ {ok, warning, critical, unknown}).
Verify: `cd apps/monitoring && .venv/bin/python -m pytest -q tests/test_alerter_sent_state.py`
Doku: keine (intern)

### T3 — process_alert auf Sent-State umstellen  [ ]
Komponente: apps/monitoring · Dateien: app/alerter.py, tests/test_alerter.py
Änderung: `process_alert` lädt den MonitorState des Checks und nutzt `resolve_notification` statt des `old == new`-Guards; Suppression-Guards (Maintenance, Host-down) returnen weiterhin OHNE `notified_status` zu ändern (Diskrepanz bleibt für die Nachmeldung); im Melde-Zweig wird Message/Hub-Emit mit `old = notified_status` gebaut (Nachmeldung nach Host-down liest sich als ok→critical, Maintenance-Recovery als critical→ok) und danach `notified_status = new_status` gesetzt — im selben Commit wie der Dispatch-Entscheid (Race-Hinweis in der Spec). silent_ack setzt nur das Feld. Recovery-Cooldown-Bypass und Alert-Log-Verhalten unverändert; bestehende test_alerter-Tests an die neue Semantik anpassen (unknown→ok ohne Vorgeschichte dispatcht nicht mehr).
Verify: `cd apps/monitoring && .venv/bin/python -m pytest -q tests/test_alerter.py tests/test_alerter_dispatch.py tests/test_alerter_hub.py`
Doku: keine (intern; Doku in T7)
Abhängt von: T1, T2

## Phase 3 — Aufrufpfade (Level-Trigger)

### T4 — Scheduler-Pfad: Dispatch bei Diskrepanz  [ ]
Komponente: apps/monitoring · Dateien: app/check_engine.py, tests/test_check_engine.py
Änderung: `execute_check` dispatcht `_dispatch_alert_bg` bei `eff_status != state.notified_status` statt `old_status != eff_status` — damit meldet der nächste Zyklus unterdrückte Diskrepanzen nach, sobald die Suppression weg ist; ohne Diskrepanz weiterhin kein Dispatch (kein Mehr-Load: der Vergleich nutzt den ohnehin geladenen State).
Verify: `cd apps/monitoring && .venv/bin/python -m pytest -q tests/test_check_engine.py` (neuer Test: gleichbleibender Status mit abweichendem notified_status dispatcht; übereinstimmender nicht)
Doku: keine (intern)
Abhängt von: T3

### T5 — Push-Pfad: Dispatch bei Diskrepanz  [ ]
Komponente: apps/monitoring · Dateien: app/routers/agent.py, tests/test_agent_report.py
Änderung: Die `pending_alerts`-Sammlung im Agent-Push-Handler nutzt dieselbe Bedingung (`eff_status != state.notified_status`); der Row-Lock-Abschnitt bleibt unverändert.
Verify: `cd apps/monitoring && .venv/bin/python -m pytest -q tests/test_agent_report.py` (neuer Test: Push ohne Statuswechsel, aber mit Diskrepanz → Dispatch)
Doku: keine (intern)
Abhängt von: T3

## Phase 4 — Szenario-Absicherung

### T6 — End-to-End-Szenarien F1/F2/F7  [ ]
Komponente: apps/monitoring · Dateien: tests/test_alerter_sent_state.py
Änderung: Integrations-Tests (client_db-Fixture-Stil) für die drei Fehlerbilder: (F1) Metrik-Check geht critical WÄHREND agent_ping critical (unterdrückt), agent_ping recovered, nächste Evaluation meldet den weiter kritischen Check nach — und keine Recovery ohne vorherige Meldung; (F2) Alert vor Maintenance-Fenster, Recovery im Fenster → Nachmeldung der Recovery nach Fensterende; Transition komplett im Fenster → dauerhaft still; Problem überdauert das Fenster → Nachmeldung; (F7) ok→unknown→ok mehrfach → null Meldungen; critical→unknown→ok → genau eine Recovery.
Verify: `cd apps/monitoring && .venv/bin/python -m pytest -q tests/test_alerter_sent_state.py && .venv/bin/python -m pytest -q tests/`
Doku: keine (intern)
Abhängt von: T4, T5

## Phase 5 — Doku

### T7 — Doku DE+EN + CHANGELOG  [ ]
Komponente: docs + Root · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, CHANGELOG.md
Änderung: Admin „Alert-Verhalten" DE+EN: Nachmeldung nach Host-down-Release und Maintenance-Fensterende (Latenz ≤ Check-Intervall), Maintenance-Callout präzisieren (Transitionen komplett IM Fenster bleiben stumm, überdauernde Zustände und Recoveries werden nachgemeldet), unknown→ok-Regel ersetzen (Recovery nur nach real gemeldetem Problem). Developer DE+EN: `notified_status`-Feld + neue Guard-/Entscheidungsreihenfolge. CHANGELOG (Changed, Unreleased-Sektion des Overhaul-Branches erweitern).
Verify: `grep -q "notified_status" docs/developer/monitoring.html docs/en/developer/monitoring.html && ! grep -q "wird als normale Recovery zugestellt" docs/admin/monitoring.html`
Doku: ist die Doku
Abhängt von: T6
