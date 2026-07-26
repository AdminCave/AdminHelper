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

### T1 — notified_status: Spalte + Migration mit Backfill  [x] (Spalte + Backfill-Migration c1d3e5f7a9b1, Smoke inkl. Backfill-Test mit Postgres 3 passed — 0ee1d3b)
Komponente: apps/monitoring · Dateien: app/models.py, alembic/versions/<neu>_notified_status.py
Änderung: `MonitorState.notified_status` (String, nullable) — der zuletzt real gemeldete Status. Alembic-Revision nach Head `b7d9f1a3c5e7`; Upgrade backfillt `notified_status = status` (Bestand gilt als gemeldet → kein Nachmelde-Sturm beim Deploy), Downgrade droppt die Spalte. `to_dict()` gibt `notifiedStatus` additiv mit aus.
Verify: `cd apps/monitoring && .venv/bin/python -m pytest -q tests/ -k "alembic or smoke"` (Parity-Smoke grün) `&& .venv/bin/python -m pytest -q tests/`
Doku: keine (intern; Doku in T7)

## Phase 2 — Kernlogik

### T2 — Reine Entscheidungsfunktion resolve_notification  [x] (24er-Matrix + Diskrepanz-Erhalt-Test, 25 passed)
Komponente: apps/monitoring · Dateien: app/alerter.py, tests/test_alerter_sent_state.py (neu, SPDX-Header)
Änderung: Pure Funktion (z. B. `resolve_notification(notified_status, new_status) -> "notify" | "silent_ack" | "skip"`): `new == notified` → skip; `new == "unknown"` → skip (notified unverändert); `new == "ok"` mit `notified ∉ {warning, critical}` → silent_ack (notified still auf ok, keine Meldung — deckt pending/NULL-Erststart und unknown-Flapping ab); sonst notify. Vollständige Matrix-Tests (notified ∈ {None, pending, ok, warning, critical, unknown} × new ∈ {ok, warning, critical, unknown}).
Verify: `cd apps/monitoring && .venv/bin/python -m pytest -q tests/test_alerter_sent_state.py`
Doku: keine (intern)

### T3 — process_alert auf Sent-State umstellen  [x] (resolve_notification verkabelt, reported_old-Semantik, silent_ack-Write getestet; Review: 2 wichtig + 2 nits gefixt)
Komponente: apps/monitoring · Dateien: app/alerter.py, tests/test_alerter.py
Änderung: `process_alert` lädt den MonitorState des Checks und nutzt `resolve_notification` statt des `old == new`-Guards; Suppression-Guards (Maintenance, Host-down) returnen weiterhin OHNE `notified_status` zu ändern (Diskrepanz bleibt für die Nachmeldung); im Melde-Zweig wird Message/Hub-Emit mit `old = notified_status` gebaut (Nachmeldung nach Host-down liest sich als ok→critical, Maintenance-Recovery als critical→ok) und danach `notified_status = new_status` gesetzt — im selben Commit wie der Dispatch-Entscheid (Race-Hinweis in der Spec). silent_ack setzt nur das Feld. Recovery-Cooldown-Bypass und Alert-Log-Verhalten unverändert; bestehende test_alerter-Tests an die neue Semantik anpassen (unknown→ok ohne Vorgeschichte dispatcht nicht mehr).
Verify: `cd apps/monitoring && .venv/bin/python -m pytest -q tests/test_alerter.py tests/test_alerter_dispatch.py tests/test_alerter_hub.py`
Doku: keine (intern; Doku in T7)
Abhängt von: T1, T2

## Phase 3 — Aufrufpfade (Level-Trigger)

### T4 — Scheduler-Pfad: Dispatch bei Diskrepanz  [x] (resolve_notification an der Callsite statt nackter Diskrepanz — verhindert No-op-BG-Tasks; silent_ack inline; with_for_update in process_alert gegen Doppel-Dispatch)
Komponente: apps/monitoring · Dateien: app/check_engine.py, tests/test_check_engine.py
Änderung: `execute_check` dispatcht `_dispatch_alert_bg` bei `eff_status != state.notified_status` statt `old_status != eff_status` — damit meldet der nächste Zyklus unterdrückte Diskrepanzen nach, sobald die Suppression weg ist; ohne Diskrepanz weiterhin kein Dispatch (kein Mehr-Load: der Vergleich nutzt den ohnehin geladenen State).
Verify: `cd apps/monitoring && .venv/bin/python -m pytest -q tests/test_check_engine.py` (neuer Test: gleichbleibender Status mit abweichendem notified_status dispatcht; übereinstimmender nicht)
Doku: keine (intern)
Abhängt von: T3

### T5 — Push-Pfad: Dispatch bei Diskrepanz  [x] (spiegelbildlich zu T4 unter dem bestehenden Row-Lock; Catch-up-Test mit cooldown 0 — Rule-Cooldown dämpft Eskalations-Nachmeldungen korrekt, wird in T7 dokumentiert)
Komponente: apps/monitoring · Dateien: app/routers/agent.py, tests/test_agent_report.py
Änderung: Die `pending_alerts`-Sammlung im Agent-Push-Handler nutzt dieselbe Bedingung (`eff_status != state.notified_status`); der Row-Lock-Abschnitt bleibt unverändert.
Verify: `cd apps/monitoring && .venv/bin/python -m pytest -q tests/test_agent_report.py` (neuer Test: Push ohne Statuswechsel, aber mit Diskrepanz → Dispatch)
Doku: keine (intern)
Abhängt von: T3

## Phase 4 — Szenario-Absicherung

### T6 — End-to-End-Szenarien F1/F2/F7  [x] (7 Szenario-Tests über die echte Pipeline, mutationstestfest; conftest-client_db wiederverwendet)
Komponente: apps/monitoring · Dateien: tests/test_alerter_sent_state.py
Änderung: Integrations-Tests (client_db-Fixture-Stil) für die drei Fehlerbilder: (F1) Metrik-Check geht critical WÄHREND agent_ping critical (unterdrückt), agent_ping recovered, nächste Evaluation meldet den weiter kritischen Check nach — und keine Recovery ohne vorherige Meldung; (F2) Alert vor Maintenance-Fenster, Recovery im Fenster → Nachmeldung der Recovery nach Fensterende; Transition komplett im Fenster → dauerhaft still; Problem überdauert das Fenster → Nachmeldung; (F7) ok→unknown→ok mehrfach → null Meldungen; critical→unknown→ok → genau eine Recovery.
Verify: `cd apps/monitoring && .venv/bin/python -m pytest -q tests/test_alerter_sent_state.py && .venv/bin/python -m pytest -q tests/`
Doku: keine (intern)
Abhängt von: T4, T5

## Phase 5 — Doku

### T7 — Doku DE+EN + CHANGELOG  [x] (4 HTML-Seiten + CHANGELOG; fachlich gegen Code verifiziert; Widerspruch im alten unknown-Eintrag gefixt)
Komponente: docs + Root · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, CHANGELOG.md
Änderung: Admin „Alert-Verhalten" DE+EN: Nachmeldung nach Host-down-Release und Maintenance-Fensterende (Latenz ≤ Check-Intervall), Maintenance-Callout präzisieren (Transitionen komplett IM Fenster bleiben stumm, überdauernde Zustände und Recoveries werden nachgemeldet), unknown→ok-Regel ersetzen (Recovery nur nach real gemeldetem Problem). Developer DE+EN: `notified_status`-Feld + neue Guard-/Entscheidungsreihenfolge. CHANGELOG (Changed, Unreleased-Sektion des Overhaul-Branches erweitern).
Verify: `grep -q "notified_status" docs/developer/monitoring.html docs/en/developer/monitoring.html && ! grep -q "wird als normale Recovery zugestellt" docs/admin/monitoring.html`
Doku: ist die Doku
Abhängt von: T6

## Phase 6 — Abschluss-Review-Findings (14 distinkt, xhigh)

### T8 — claim-then-dispatch in process_alert  [x] (Claim-Commit vor Kanal-I/O, current unter Lock re-gelesen, at-most-once; Reihenfolge-Assert im Test)
Fixt F1 (FOR-UPDATE-Lock umspannte die Kanal-I/O — Regression gegen die 5.3-Isolation), F2 (Stale-Snapshot: BG-Task dispatcht Caller-new_status statt state.status → Phantom-Transitionen bei Out-of-order-Dispatches) und F5 (Commit-Fehler nach Versand → Re-Dispatch). Claim-Phase unter kurzem Lock: current = state.status re-lesen, resolve, Guards, notified_status-Write + Commit VOR der Kanal-I/O (at-most-once); Log-Rows danach via Caller-Commit.
Verify: pytest tests/test_alerter*.py (neuer Doppel-Dispatch-Skip-Test + Stale-Snapshot-Test)

### T9 — Backfill konsultiert Alert-Log für unknown-Rows  [x] (COALESCE-Subquery, Smoke-Matrix c1/c2/c3 mit Postgres grün)
Fixt F3: unknown-Rows backfillen aus dem letzten monitor_alert_log-Eintrag (der real gesendete Status), Fallback 'unknown' — die critical→unknown→ok-Recovery über den Deploy hinweg geht nicht mehr verloren. + Smoke-Test-Fall.
Verify: DATABASE_URL pytest tests/test_migrations_smoke.py

### T10 — Test-Lücken F8/F9  [x] (Doppel-Dispatch-Skip, Stale-Snapshot mit committed-at-dispatch, Scheduler-silent_ack)
Skip-Guard mit State-Row (Doppel-Dispatch-No-op) und silent_ack im Scheduler-Pfad (notified_status=ok in DB, kein Submit) pinnen.
Verify: pytest tests/test_alerter.py tests/test_check_engine.py

### T11 — Doku-/Kommentar-Korrekturen F6/F7/F11  [x] (Host-down-Obergrenze, Hub-Sektion sent-state, Dev-Doku claim-then-dispatch, 3 stale Kommentare)
Admin DE+EN: Host-down-Catch-up-Obergrenze präzisieren (agent_ping muss erst wieder ok melden → Obergrenze agent_ping-Intervall + Check-Intervall); Hub-Sektion („Was löst eine Benachrichtigung aus") auf Sent-State; Dev-Doku-Lock-Absatz auf claim-then-dispatch. Stale Docstrings/Kommentare (alerter.py-Modul, agent.py, _helpers.py).
Verify: grep-Checks + HTML-Balance

### T12 — Ledger committen  [x] (dieser Commit)
Fixt F10: die Task-Abhaken T1–T7 waren nur im Working Tree.
Verify: git show HEAD:tasks/alert-sent-state.md zeigt [x]

Merker (bewusst kein Fix): F4 No-op-Task-Churn während langer Suppressionen — nach T8 sind No-ops Millisekunden-billig; ein Dedup über die zwei Task-Mechanismen (Pool + FastAPI BackgroundTasks) wäre fehleranfällige Komplexität. F12 (_build_message-Re-SELECT) ist nach T8 korrekt so (State nach Claim-Commit expired). F13 (old_status-Parameter) bleibt als notified-Fallback der Fake-DB-Tests. F14 (Smoke-Test-Gerüst 3× kopiert) — Aufräumer bei der nächsten Migration.

