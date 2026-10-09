<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring-Zeitstempel in UTC mit `Z` — Task-Ledger
Status: bereit · Branch: feature/monitoring-utc-z · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-09 (kleines Fund-Paket aus R-0202, von Kevin am 2026-10-06 angenommen: „nach R-0064, gleiches Muster“ — das deckt den API-Vertrag samt Altzeilen-Grenze; Delegation Kevin 2026-10-05). Offene Fragen entschieden (Aufsicht): 1 Weg (b), formatCheckTime liest einen Wert ohne Zone als UTC wie die drei Wartungs-Leser; 2 Heavy none, keine Integrations- oder E2E-Stufe liest Monitoring-Zeitstempel; 3 Zuständigkeit wie oben
Spec: Roadmap R-0202 (Kurz-Ledger ohne Spec)
Heavy: none — Monitoring-Dienst und Desktop-UI, kein Stack-, Gateway-, PKI- oder Install-Pfad; der Server-Proxy reicht die Antworten byteweise durch, und keine Integrations- oder E2E-Stufe liest Monitoring-Zeitstempel (offene Frage 2).
DoD je Task: CLAUDE.md (Tests grün, ruff check und ruff format sauber bzw. eslint/prettier und svelte-check, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-09 von Worker B im Auftrag der Aufsicht (adminhelper-ac) aus einer Zeile, die Kevin in der Triage vom
2026-10-06 angenommen hat („nach R-0064, gleiches Muster“). Die private Roadmap ist in diesem Worktree nicht lesbar;
der Zeileninhalt kommt von der Aufsicht. Muster: R-0064 (#87, `iso_utc` in `apps/server/app/core/time.py:47-55`).
Zeilenangaben origin/main@b64253ca.

Leser, gegen origin/main geprüft (Lehre aus R-0201: Schreiber umstellen reicht nicht):
- Desktop-UI, `formatCheckTime` (`lib/models/monitoring.ts:124-135`, `new Date(isoStr)` ohne Korrektur) für
  `lastCheck` (`MonCheckLine.svelte:82`) und `sentAt` (`MonitoringLog.svelte:19`). Heute liest es den Wert ohne Zone
  als Ortszeit und zeigt die UTC-Uhrzeit als lokale, in Europe/Berlin also zwei Stunden zu früh. Mit `Z` richtig.
- Desktop-UI, Wartungsfenster: `lib/models/maintenance.ts:46-47`, `MaintenanceModal.svelte:53` und
  `MonitoringTab.svelte:155` hängen `Z` nur an, wenn es fehlt (`endsWith('Z')`). Mit `Z` richtig, kein `…ZZ`.
  An `+00:00` brächen sie (`…+00:00Z` ist Invalid Date), deshalb schreibt T1 `Z`, nicht `+00:00`.
  Der Schreibweg (`localInputToUtcIso`, `toISOString()`) und `_naive_utc` in `apps/monitoring/app/schemas.py:215-227`
  bleiben unberührt.
- Desktop-Rust: reicht die Antworten als `serde_json::Value` durch (`proxy.rs:44`, `:89`). Nicht betroffen.
- Web: hat keine Monitoring-Seite (`src/routes.ts:14-19`). Nicht betroffen.
- Server: Der Proxy gibt `resp.content` unverändert zurück (`monitoring_proxy/router.py:76-80`, `:140-145`).
  `provisioning/helpers.py:65-67` liest nur `apiKey`. Nicht betroffen.
- Monitoring selbst: liest keine eigene `to_dict`-Ausgabe zurück. Hub-Event (`alerter.py:251-262`) und
  Webhook-Payload (`alerter.py:403-406`) tragen keine Zeitstempel. Metriken sind Epoch-Werte.
- Altzeilen: Vor NEU-8.14b (fd98f55a, 2026-07-09) konnte ein `server_default` Berliner Ortszeit speichern.
  Betroffen wären nur `createdAt`/`updatedAt` aus dieser Zeit. Sie erscheinen mit `Z` um den Offset verschoben;
  keine Oberfläche zeigt sie. Das ist dieselbe Grenze wie bei R-0064 (keine Migration).

### T1 — Monitoring: Zeitstempel der Antworten in UTC mit `Z` (R-0202)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/core/time.py, apps/monitoring/app/models.py, apps/monitoring/tests/test_core_time.py, apps/monitoring/tests/test_models_timestamps.py, apps/monitoring/tests/test_maintenance_router.py
Evidenz: run.sh[quick] monitoring: 4 passed, 0 failed, 14 skipped @73d65055 2026-10-09T10:58:48+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung: Die 13 `to_dict`-Stellen in `apps/monitoring/app/models.py` schreiben `.isoformat()` eines naiven
UTC-Werts, also ohne Zone: `:55`, `:56`, `:82`, `:83`, `:124`, `:125`, `:161`, `:193`, `:194`, `:278`, `:324`, `:325`, `:331`.
- `iso_utc(dt)` kommt in `apps/monitoring/app/core/time.py`, mit derselben Semantik wie die Server-Kopie:
  - `None` bleibt `None`;
  - ein naiver Wert ist UTC (Konvention des Dienstes);
  - ein Wert mit Zone wird nach UTC umgerechnet;
  - der Wert endet auf `Z`, nicht auf `+00:00`.
- `UtcDatetime` kommt nicht mit, denn der Dienst hat kein `response_model`.
- Alle 13 Stellen rufen `iso_utc`.
- Kein Leser ändert sich (siehe oben); die Antworten bleiben untypisiert, der OpenAPI-Snapshot bleibt gleich.

Tests:
- `test_core_time.py`: `iso_utc` mit naivem Wert (`…Z`), mit Offset `+02:00` (umgerechnet), mit Mikrosekunden,
  mit `None` und mit dem Jahr 1.
- Neue Datei `tests/test_models_timestamps.py` mit SPDX-Kopf (`reuse annotate --copyright "Kevin Stenzel" --license
  GPL-3.0-or-later`):
  - Sie geht über die Modelle mit `to_dict` und setzt jede `DateTime`-Spalte auf einen naiven Wert.
  - Sie verlangt, dass jedes Zeitfeld der Ausgabe auf `Z` endet und denselben Zeitpunkt trägt.
  - So fällt auch eine künftige `to_dict`-Stelle ohne `iso_utc` auf. Rot vor dem Fix.
- `test_maintenance_router.py`: Die drei Assertions auf das Format ohne Zone erwarten `Z`. Das sind `:86` und
  `:87` (`2026-07-19T12:00:00`, `…14:00:00`) und `:112` (`0001-01-01T00:00:00`).
Assertion-Änderung: apps/monitoring/tests/test_maintenance_router.py::test_aware_datetimes_normalize_to_naive_utc — die Antwort trägt `startsAt`/`endsAt` jetzt mit `Z` (R-0202), der Zeitpunkt bleibt gleich; apps/monitoring/tests/test_maintenance_router.py::test_a_naive_year_one_stays_valid — `startsAt` des Jahres 1 trägt jetzt `Z` (R-0202), der Wert bleibt gleich
Beweis: origin/main@b64253ca, in `apps/monitoring` mit dem devenv und `DATA_DIR` auf ein eigenes Verzeichnis:
`MonitorState(last_check=datetime(2026, 10, 9, 8, 15)).to_dict()["lastCheck"]` → `2026-10-09T08:15:00`, ohne Zone.
Dasselbe gilt für `MonitorAlertLog.sentAt` und `MonitorMaintenance.startsAt`.
HEAD: b64253ca
Semantik:
- `docs/developer/api-reference.html:50`: „Zeitstempel in Antworten sind RFC 3339 in UTC mit `Z`, z. B.
  `2026-10-05T12:00:00Z` – auch dort, wo das Schema sie als `string` führt.“
- Die Ausnahme `:55` „Die Antworten unter `/api/monitoring/*` reicht der Proxy unverändert vom Monitoring-Dienst
  durch“ hält den heutigen Stand fest, nicht ein gewolltes Format.
- Die R-0064-Spec (`docs/features/tz-aware-datetimes.md`, offene Frage 6) empfahl dafür eine eigene Zeile. Kevin hat
  sie am 2026-10-06 angenommen.
Verify: bash scripts/dev/verify.sh monitoring --strict
Doku: in T3 (API-Referenz DE+EN, CHANGELOG)

### T2 — Desktop: `formatCheckTime` liest einen Wert ohne Zone als UTC, Tests mit `Z`  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/models/monitoring.ts, apps/desktop/ui/src/lib/models/monitoring.test.ts, apps/desktop/ui/src/lib/models/maintenance.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped · contracts: 1 ok @0000f16c 2026-10-09T11:26:43+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung: Der Plan folgt der Empfehlung zu offener Frage 1, Weg (b).
- `formatCheckTime` (`lib/models/monitoring.ts:124-135`) hängt `Z` an, wenn es fehlt, wie die drei
  Wartungs-Leser (`maintenance.ts:46-47`). Damit zeigt der Desktop die Check- und Alarmzeiten auch gegen einen
  Monitoring-Dienst von vor T1 richtig.
- Bei Weg (a) entfällt die Code-Änderung, und die Task bringt nur die Tests.

Tests:
- `monitoring.test.ts`, neuer `describe` für `formatCheckTime`:
  - Ein Wert mit `Z` und derselbe Wert ohne Zone ergeben dieselbe Anzeige, nämlich die des UTC-Zeitpunkts in
    der Ortszeit.
  - `null`, `undefined` und ein unlesbarer Wert ergeben `-`.
  - Der Test legt eine Zeitzone ungleich UTC fest (etwa `Europe/Berlin` über `process.env.TZ` bzw. `vi.stubEnv`).
    Sonst ist er auf einer UTC-Maschine wie der CI auch ohne die Änderung grün. Rot vor der Änderung, bei Weg (b).
- `maintenance.test.ts`: ein neuer Fall, in dem `isWindowActive` ein Fenster mit `startsAt`/`endsAt` auf `Z`
  richtig auswertet (kein `…ZZ`). Der bestehende Fall ohne Zone (`:45`) bleibt unverändert.
Beweis: origin/main@b64253ca, `sed -n 126p apps/desktop/ui/src/lib/models/monitoring.ts` → `const d = new
Date(isoStr);`. Ein String ohne Zone gilt nach ECMAScript als Ortszeit. Die R-0064-Spec hielt fest, dass der
Desktop die Monitoring-Zeiten verschoben zeigt (`docs/features/tz-aware-datetimes.md`, offene Frage 6).
HEAD: b64253ca
Semantik: wie T1. Die Desktop-Doku beschreibt die Anzeige nicht. Gesucht wurde in `docs/developer/desktop.html` und
`docs/admin/monitoring.html` nach Zeitzone und Uhrzeit.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: in T3 (CHANGELOG)

### T3 — Doku: Monitoring-Antworten in UTC mit `Z`  [x]
Komponente: monitoring · Dateien: docs/developer/api-reference.html, docs/en/developer/api-reference.html, CHANGELOG.md
Evidenz: run.sh[quick] monitoring: 4 passed, 0 failed, 14 skipped · contracts: 1 ok @6722c904 2026-10-09T11:28:29+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung:
- Die Ausnahme zu `/api/monitoring/*` in „Zeitstempel“ bzw. „Timestamps“ fällt weg: DE und EN je
  `api-reference.html:55`. Die Regel in `:50` gilt dann auch dort.
- CHANGELOG unter `[Unreleased]` → `### Fixed`, eine Zeile nach dem Vorbild von R-0064:
  - Die Monitoring-Antworten schreiben Zeitstempel als RFC 3339 in UTC mit `Z`, bisher ohne Zone.
  - Der Desktop zeigte Check- und Alarmzeiten um den Abstand zu UTC verschoben.
  - Hinweis für eigene Skripte gegen `/api/monitoring/*`: Ein Skript, das die Werte als String vergleicht, muss das
    `Z` erwarten. `datetime.fromisoformat` liest beide Formen.
  - Keine Migration; Werte von vor dem 2026-07-09 in `createdAt`/`updatedAt` können um den Offset abweichen.
Verify: bash scripts/dev/verify.sh monitoring --strict
Doku: docs/developer/api-reference.html + docs/en/developer/api-reference.html · CHANGELOG.md
Abhängt von: T1, T2

### T4 — Nachbesserung: `fromisoformat` erst ab Python 3.11, Ausnahme für die Metrik-Reihen  [x]
Komponente: monitoring · Dateien: CHANGELOG.md, docs/developer/api-reference.html, docs/en/developer/api-reference.html
Evidenz: run.sh[quick] monitoring: 4 passed, 0 failed, 14 skipped · contracts: 1 ok @f6266d1a 2026-10-09T12:34:31+02:00
Review: kein neuer Review (Doku-Nachbesserung, Aufsicht 2026-10-09)
Änderung: Aus dem Opus-Review über den Branch, von der Aufsicht freigegeben (2026-10-09), nur Doku, ohne neuen Review.
- `CHANGELOG.md`: „`datetime.fromisoformat` liest beide Formen“ gilt erst ab Python 3.11; ältere Versionen werfen bei
  `Z` einen `ValueError`. Der Satz nennt das und den Weg für ältere Versionen (`Z` vorher durch `+00:00` ersetzen),
  im Eintrag von R-0202 und ebenso im Eintrag von R-0064 („alle drei Formen“), der auch unter `[Unreleased]` steht.
- API-Referenz DE und EN, „Zeitstempel“ bzw. „Timestamps“: Ohne die Monitoring-Ausnahme deckt die Regel auch
  `GET /api/monitoring/checks/{id}/metrics` ab. Dessen `data` und `statusHistory` sind VictoriaMetrics-Reihen mit
  Paaren `[epoch, "wert"]` in Unix-Sekunden (`apps/monitoring/app/routers/checks.py`, `get_check_metrics`). Das wird
  ein eigener Aufzählungspunkt unter den Ausnahmen.
Verify: bash scripts/dev/verify.sh monitoring --strict
Doku: CHANGELOG.md · docs/developer/api-reference.html + docs/en/developer/api-reference.html
Abhängt von: T3
