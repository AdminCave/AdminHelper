# Merker-Aufräumer — Task-Ledger
Status: erledigt · Branch: feature/merker-cleanup · Commit-Granularität: pro Task · Review: pro Task (feature-review) · Modell: Opus
Spec: docs/features/merker-cleanup.md
Fast-Suite: lokal · Warm-Profil: desktop
DoD je Task: CLAUDE.md (Tests grün, ruff/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Hinweis: Klein und disjunkt — apps/monitoring (Checker + Tests), apps/desktop/ui
(eine Komponente), Ledger-Hygiene. Kein multibox nötig; am Abschluss reicht
`run.sh quick` plus `AH_ONLY='monitoring desktop-ui' crabbox_iter.sh quick`.
Die Triage der acht Merker steht in der Spec — vier sind bereits erledigt,
vier begründet geschlossen; hier stehen nur die drei offenen.

## Phase 1 — Alerting-Robustheit

### T1 — NTP-Slew-Guard für die agent_ping-Staleness  [x] (Monoton-Companion + 60s-Toleranz, 7 Tests inkl. Grenzfall/Rückwärtssprung; Review fand falsch benannte Uhr — korrigiert)
Komponente: apps/monitoring · Dateien: app/checkers/agent.py, tests/test_agent_ping_checker.py
Änderung: Neben `_last_report` (Wanduhr, persistierbar) einen prozess-lokalen Monoton-Zeitpunkt pro `server_id` führen (`record_agent_report` setzt beide). In `AgentPingChecker.run` beide Deltas bilden; weicht das Wanduhr-Delta um mehr als 60 s vom Monoton-Delta ab, gilt die Uhr als gesprungen → Baseline neu setzen (beide Werte auf jetzt), `unknown` mit Klartext-Meldung zurückgeben statt `critical`, und den Sprung einmal loggen. Fehlt der Monoton-Wert (nach Neustart aus `hydrate_agent_liveness`), bleibt es exakt beim heutigen Wanduhr-Vergleich.
Verify: `cd apps/monitoring && .venv/bin/python -m pytest -q tests/test_agent_ping_checker.py` — neue Fälle: (a) Uhr springt 2 h vor → kein `critical`, Baseline zurückgesetzt; (b) echter Ausfall (Monoton- UND Wanduhr-Delta wachsen gleich) → weiterhin `critical`; (c) hydrierter Server ohne Monoton-Wert → Verhalten unverändert.
Doku: docs/admin/monitoring.html + docs/en/… (ein Satz im Abschnitt „Alert-Verhalten"), docs/developer/monitoring.html + EN (Liveness-Absatz), CHANGELOG (Fixed) — im selben Commit

## Phase 2 — Kleinkram mit Fallenpotenzial

### T2 — MonSparkline: untrack im IntersectionObserver-Fallback  [x] (BEIDE Pfade untrackt — der Observer-Callback kann synchron feuern, Vorbild MonHeartbeatBar; Ledger-Text war zu eng. 2 Tests, je einer pro Pfad, mutationsgeprüft)
Komponente: apps/desktop/ui · Dateien: src/components/monitoring/MonSparkline.svelte
Änderung: Im `$effect` den Fallback-Zweig ohne `IntersectionObserver` auf `untrack(() => void load())` umstellen — identisch zu dem Fix, den `MonHeartbeatBar` in T22 gegen `effect_update_depth_exceeded` bekommen hat. `load()` liest `loaded`/Store-Werte; ohne `untrack` schreibt der Effekt in seine eigenen Abhängigkeiten.
Verify: `cd apps/desktop/ui && npm run check && npx vitest run src/components/monitoring/` — plus ein Test wie in MonHeartbeatBar.test.ts (IO-Stub abwesend → genau ein `load()`, keine Endlosschleife)
Doku: keine (intern)

### T3 — Smoke-Test-Gerüst deduplizieren  [x] (scratch_db-Contextmanager, 3 Kopien → 1; Nebeneffekt: das upgrade der Fixture liegt jetzt im try/finally, ein Migrationsfehler leakt die Scratch-DB nicht mehr)
Komponente: apps/monitoring · Dateien: tests/test_migrations_smoke.py
Änderung: Das dreifach kopierte Scratch-DB-Gerüst (CREATE DATABASE, `monkeypatch` auf `app_config.DATABASE_URL`, alembic-Config, `finally`-DROP mit FORCE) in einen Contextmanager `scratch_db()` ziehen; die bestehende `migrated_engine`-Fixture und die zwei Zwischenstand-Tests (uniq-dedupe, notified_status-Backfill) nutzen ihn. Verhalten und Assertions unverändert.
Verify: `source .devenv.sh && cd apps/monitoring && DATABASE_URL="$AH_TEST_DB" .venv/bin/python -m pytest -q tests/test_migrations_smoke.py` (weiterhin 3 passed) `&& .venv/bin/python -m pytest -q tests/`
Doku: keine (intern)

## Phase 3 — Ledger-Hygiene

### T4 — Erledigte und geschlossene Merker in den Ledgern markieren  [x] (7 Annotationen im Overhaul-Ledger, 1 Sammel-Annotation im Sent-State-Ledger; grep-Verify grün)
Komponente: tasks · Dateien: tasks/monitoring-overhaul.md, tasks/alert-sent-state.md
Änderung: Jeden der acht Merker mit seinem Triage-Ergebnis aus der Spec annotieren — vier als „erledigt durch <Commit/PR>", vier als „geschlossen: <Grund>", die drei hier umgesetzten als „gefixt in feature/merker-cleanup". Damit liest niemand die Ledger erneut als offene Halde.
Verify: `! grep -qE "bei Gelegenheit fixen|Fix-Kandidat" tasks/monitoring-overhaul.md tasks/alert-sent-state.md`
Doku: keine (ist Ledger-Pflege)
Abhängt von: T1, T2, T3
