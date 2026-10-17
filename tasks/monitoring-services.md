<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring: Linux-Dienste richtig zählen und melden — Task-Ledger
Status: erledigt · Branch: feature/monitoring-services · Review: pro Task
Spec: docs/features/monitoring-services.md (Roadmap R-0418)
Heavy: linux-full + windows — Agent-Report, Monitoring-Auswertung und Desktop-Anzeige im echten Stack (`run.sh integration` mit Agent-Push, `run.sh e2e` mit `desktop_e2e_monitoring.sh`) auf einer Pool-VM; `windows`, weil sich der gemeinsame Report-Pfad und `services_windows.go` (Zähler) ändern und die Go-Suite dort nativ läuft
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Kevin 2026-10-16: additive Report-Felder freigegeben (`systemd.counts`, `systemd.error`, `alias_of` im Inventar); keine Agent-Konfig-Synchronisation, der Listen-Modus wird serverseitig ausgewertet; ein Name ohne Daten im Listen-Modus zählt nicht als down und wird neutral als „nicht gefunden“ angezeigt; höchstens 50 Einzelabfragen nach einem gescheiterten Sammelaufruf; die deutschen Server-Meldungstexte sind eine eigene Roadmap-Zeile, nicht dieses Vorhaben. Gemeinsame Vertragsdateien mit R-0419/R-0420 (`report.go`, Report-Auswertung in `routers/agent.py`): wer zuerst merged, die anderen mergen `origin/main` vor dem Push.

### T1 — Agent: enabled-aber-inaktive Kandidaten nachprüfen (oneshot, Condition, Timer)  [x]
Komponente: agent · Dateien: apps/agent/internal/monitor/services_linux.go, apps/agent/internal/monitor/services_linux_test.go, docs/features/monitoring-services.md
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @93cc22d1 2026-10-16T15:07:17+02:00
Review: approve (.ah-out/review/monitoring-services/T1.verdict.json)
Änderung: Die Kandidaten aus `assembleServiceHealth` (`services_linux.go:68-73`) werden mit einem gebündelten `systemctl show -p Id,Names,Type,Result,ConditionResult,TriggeredBy -- <kandidaten>` nachgeprüft; verworfen wird eine Unit bei `Type=oneshot` und `Result=success`, bei `ConditionResult=no` oder bei nicht leerem `TriggeredBy`; fehlende oder leere Properties verwerfen nichts. Scheitert der Sammelaufruf, fragt der Agent höchstens 50 Kandidaten einzeln ab; eine gescheiterte Einzelabfrage lässt die Unit Kandidat. Die Auswertung der `show`-Blöcke ist eine reine Funktion (Muster `parseWatchedServices`, `:132-161`), der Prozessaufruf über einen Seam wie `runWithTimeout`. Tests zuerst rot, Namen mit Präfix `TestFilterEnabledInactive`: echte systemd-257-Blöcke (Spec, Abschnitt b: `e2scrub_reap` oneshot/success, `systemd-pstore` ConditionResult=no, `anacron` TriggeredBy=anacron.timer, ein normaler `Type=simple`-Dienst bleibt Kandidat); fehlende Property → bleibt; Batch-Fehler → Einzelabfrage über den Seam; mehr als 50 Kandidaten → Rest ungeprüft.
Verify: bash scripts/dev/verify.sh agent --strict -- -run TestFilterEnabledInactive
Doku: keine (intern; sichtbar mit T8)
Beweis: origin/main@af4498a7 · Lab Ubuntu 24.04: frische Box `warning` mit 17 Units („Inaktiv (autostart)“); `systemctl show` auf Debian 13 (systemd 257) siehe Spec
Dedup-Key: bug:monitoring:checkers/agent.py:services-display
HEAD: af4498a7

### T2 — Agent: Zähler, sortiertes Inventar, systemctl-Fehler sichtbar  [x]
Komponente: agent · Dateien: apps/agent/internal/monitor/services.go, apps/agent/internal/monitor/services_test.go, apps/agent/internal/monitor/services_linux.go, apps/agent/internal/monitor/services_windows.go, apps/agent/internal/monitor/services_linux_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @d5224fc9 2026-10-16T15:21:21+02:00
Review: approve (.ah-out/review/monitoring-services/T2.verdict.json)
Änderung: Neuer reiner Helfer in `services.go` (ohne Build-Tag): `serviceCounts(entries)` zählt `.service`-Einträge mit `active_state == "active"` und gesamt; `collectServiceHealth` (Linux `services_linux.go:14-38`, Windows `services_windows.go:24-41`) legt `counts: {"active", "total"}` in den `systemd`-Block. `assembleServiceHealth` sortiert `all_services` nach `unit` (heute Map-Reihenfolge, `:51-66`). Scheitert `systemctl list-units` (`parseSystemctlColumns` verschluckt den Fehler, `:87-93`), setzt der Linux-Collector `error` mit kurzem Grund (ohne Pfade/Secrets). Neue Testdatei `services_test.go` mit SPDX-Header (`// SPDX-FileCopyrightText: 2026 Kevin Stenzel` / `//` / `// SPDX-License-Identifier: GPL-3.0-or-later`); Tests zuerst rot, Namen mit Präfix `TestServiceHealth` (z. B. `TestServiceHealthCounts`, `TestServiceHealthSorted`, `TestServiceHealthSystemctlError`).
Verify: bash scripts/dev/verify.sh agent --strict -- -run TestServiceHealth
Doku: keine (intern; sichtbar mit T8)
Abhängt von: T1

### T3 — Agent: Aliase im Inventar (`alias_of`) und robuster Legacy-Watch-Pfad  [x]
Komponente: agent · Dateien: apps/agent/internal/monitor/services_linux.go, apps/agent/internal/monitor/services_linux_test.go, apps/agent/internal/monitor/inventory.go, apps/agent/internal/monitor/services.go, apps/agent/internal/monitor/services_windows.go, apps/agent/internal/monitor/scquery.go, apps/agent/internal/monitor/scquery_test.go, apps/agent/internal/monitor/inventory_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @fe8891ec 2026-10-16T15:37:54+02:00
Review: approve (.ah-out/review/monitoring-services/T3.verdict.json)
Änderung: Einträge aus `list-unit-files` mit Zustand `alias` (ohne Template-Namen `*@.service`) werden mit einem gebündelten `systemctl show -p Id -- <aliase>` aufgelöst und bekommen `alias_of`; `inventoryHash` (`inventory.go:33-41`) bezieht `alias_of` ein. `collectWatchedServices` (`services_linux.go:108-126`) fragt nach einem Batch-Fehler jeden Namen einzeln ab statt alle als down zu melden; `parseWatchedServices` (`:132-161`) ordnet zusätzlich über `Names` zu (`sshd` → Block mit `Id=ssh.service`, `Names=ssh.service sshd.service`), dafür `-p Id,Names,ActiveState,MainPID`. Tests zuerst rot, Namen mit Präfix `TestAliasAndWatch`: Alias-Auflösung; Template-Name im Batch → Einzelabfrage, die übrigen Namen korrekt; `sshd` läuft über `Names`.
Verify: bash scripts/dev/verify.sh agent --strict -- -run TestAliasAndWatch
Doku: keine (intern; sichtbar mit T8)
Abhängt von: T2

### T4 — Monitoring: Auto-Modus nimmt die Agent-Liste, Zähler, Glob-ignore, systemctl-Fehler  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/checkers/agent.py, apps/monitoring/tests/test_service_process_checker.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @914247cc 2026-10-16T15:52:53+02:00
Review: approve (.ah-out/review/monitoring-services/T4.verdict.json)
Änderung: `_evaluate_auto` (`checkers/agent.py:374-442`) übernimmt `systemd.enabled_inactive` unverändert und berechnet es nicht mehr aus `all_services` (`:401-405`); `failed` = `systemd.failed` ∪ failed aus dem gekappten Inventar wie heute. `counts` → `_details.active_count`/`total` (nur wenn vorhanden und ganzzahlig ≥ 0). `systemd.error` → `unknown` mit Grund statt „Alle systemd-Units OK“. `_is_ignored` (`:364-372`) vergleicht per `fnmatch.fnmatchcase`, mit derselben `.service`-Normalisierung. Tests zuerst rot: voller und gedrosselter Push liefern dasselbe Ergebnis (Agent-Liste maßgeblich, auch wenn `all_services` mehr inaktive Units enthält); Zähler landen in `_details`; ungültige Zähler werden ignoriert; `error` → `unknown`; `ignore: ["drkonqi-coredump-processor@*"]` blendet eine Instanz aus; der bestehende Test `test_auto_mode_full_and_throttled_report_agree` bleibt grün.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_service_process_checker.py
Doku: keine (intern; sichtbar mit T8)
Abhängt von: T2
Beweis: origin/main@af4498a7 · `git grep -n active_count origin/main -- apps` → nur `SecServices.svelte:44`; `checkers/agent.py:394-405` berechnet `enabled_inactive` bei vollem Inventar selbst
Dedup-Key: bug:monitoring:checkers/agent.py:services-display
HEAD: af4498a7

### T5 — Monitoring: Listen-Modus serverseitig aus Inventar und letztem Stand  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/checkers/agent.py, apps/monitoring/app/routers/agent.py, apps/monitoring/tests/test_service_process_checker.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @18fef8b0 2026-10-16T16:14:00+02:00
Review: approve (.ah-out/review/monitoring-services/T5.verdict.json)
Änderung: `_evaluate_list` (`checkers/agent.py:444-478`) bekommt `prev_details` und wertet je Name nach Spec (c): normalisieren (`.service`), Quelle `report["services"]` → `systemd.all_services` (über `unit` oder `alias_of`) → `prev_details.watched`, sonst `nodata`; `_details.watched` = `[{name, state}]` mit `state ∈ running|down|nodata`; Status `critical` bei mindestens einem `down`, `unknown`, wenn kein Name Daten hat, sonst `ok`. Der Push-Pfad (`routers/agent.py:226-238`) reicht `prev_details` auch an `service_process` (Menge statt Einzelvergleich mit `agent_resources`). Tests zuerst rot: Agent ohne `--services` und Name im Inventar → `running`; Alias `sshd` über `alias_of`; gedrosselter Push übernimmt den letzten Stand; neuer Name ohne Inventar → `nodata`, kein `critical`; Legacy `report["services"]` hat Vorrang; über den TestClient (Fixture `client_db`) erreicht `prev_details` den Checker; `test_list_mode_unaffected_by_throttling` bleibt grün.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_service_process_checker.py
Doku: keine (intern; sichtbar mit T8)
Abhängt von: T3, T4
Beweis: origin/main@af4498a7 · `provision.go:139-143` übergibt keine Dienste, `report.go:52-59` lässt `services` ohne Namen weg, `checkers/agent.py:450` liest nur `report["services"]` → jeder Name `down`
Dedup-Key: bug:monitoring:checkers/agent.py:services-display
HEAD: af4498a7

### T9 — Agent: nicht installierte, inaktive Units nicht ins Inventar  [x]
Komponente: agent · Dateien: apps/agent/internal/monitor/services_linux.go, apps/agent/internal/monitor/services_linux_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @4f91399d 2026-10-16T16:20:27+02:00
Review: approve (.ah-out/review/monitoring-services/T9.verdict.json)
Änderung: `collectServiceHealth` (`services_linux.go:17`) lässt Units mit Load-State `not-found` und Active-State `inactive` aus `all_services` weg: `list-units --all` listet sie nur, weil eine andere Unit sie referenziert, `list-unit-files` kennt sie nicht, und im Inventar wären sie `{inactive, unknown}`, also für den Listen-Modus `down` statt `nodata` (Spec (c)3). Eine `not-found`-Unit, die `active` oder `failed` ist, bleibt; scheitert `list-units`, ändert sich nichts. `failed` und `enabled_inactive` bleiben unberührt. Tests zuerst rot, Namen mit Präfix `TestServiceHealthNotFound`, über den Seam `runSystemctl` mit echten `list-units`-Zeilen: `firewalld.service not-found inactive dead` fehlt im Inventar; `gone.service not-found active running` und `old.service not-found failed failed` bleiben; eine geladene inaktive Unit bleibt.
Verify: bash scripts/dev/verify.sh agent --strict -- -run TestServiceHealthNotFound
Doku: keine (intern; sichtbar mit T8)
Abhängt von: T3
Beweis: Reviewer T5 (2026-10-16), Inventar aus den echten systemctl-Ausgaben einer Debian-13-Box: `services: ["firewalld"]` (nicht installiert, referenziert) → `critical`, der Tippfehler `["firewalldd"]` → `unknown`/`nodata`
Dedup-Key: bug:monitoring:checkers/agent.py:services-display
HEAD: f7f0836e

### T6 — Desktop: Dienste-Zeile mit ehrlichen Zahlen, neutralem Zustand und Übersetzungen  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/monitoring/section/SecServices.svelte, apps/desktop/ui/src/components/monitoring/section/SecServices.test.ts, apps/desktop/ui/src/lib/api/types.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @c1a5cfd9 2026-10-16T16:38:13+02:00
Review: approve (.ah-out/review/monitoring-services/T6.verdict.json)
Änderung: `info()` (`SecServices.svelte:33-59`) liest `active_count`/`total` nur, wenn vorhanden; ohne Details eine neutrale Pille „Noch keine Daten“ (kein `pill-crit`, `:35`); Pillenfarbe aus `check.state.status` (dieselbe Quelle wie der Punkt), Liste aus `_details`; Listen-Modus liest `watched` in beiden Formen (`running: bool` alt, `state` neu) und zeigt `nodata` neutral als „nicht gefunden“ (`monitoring.services.note.nodata`, EN „not found“); Hinweise `failed`/`inactive`/`down`/`nodata` über neue Schlüssel `monitoring.services.note.*` (DE neben `dictionaries.ts:577-580`, EN neben `:1199-1202`); „x/y aktiv“ nur mit Zählern; `MonitorServiceDetails` (`types.ts:282-287`) um `active_count`, `total` und `state` erweitern. Neue Testdatei mit SPDX-Header (`// SPDX-FileCopyrightText: 2026 Kevin Stenzel` / `//` / `// SPDX-License-Identifier: GPL-3.0-or-later`), zuerst rot: ohne Details neutral; Auto mit Zählern „41/63“; Auto ohne Zähler nur Problemzahl; Status `ok` bei Rohproblemen (gedämpfter erster Fehler) → keine rote Pille; Listen-Modus alt und neu; `nodata` neutral als „nicht gefunden“, nie rot; übersetzte Hinweise in DE und EN.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/monitoring/section/SecServices.test.ts
Doku: keine (intern; sichtbar mit T8)
Abhängt von: T4, T5
Beweis: origin/main@af4498a7 · Lab-Render „17 Probleme“ (rot) und „0/17 laufen“ auf einer sauberen Box; `SecServices.svelte:44`
Dedup-Key: bug:monitoring:checkers/agent.py:services-display
HEAD: af4498a7

### T7 — Desktop: Platzhalter und Hinweis im Check-Editor  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/monitoring/CheckConfigFields.svelte, apps/desktop/ui/src/components/monitoring/CheckConfigFields.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/components/monitoring/section/SecServices.svelte, apps/desktop/ui/src/components/monitoring/section/SecServices.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @985a5f0e 2026-10-16T16:58:14+02:00
Review: approve (.ah-out/review/monitoring-services/T7.verdict.json)
Änderung: Im Listen-Modus (`CheckConfigFields.svelte:282-291`) ein kurzer übersetzter Hinweis unter dem Feld (Namen mit oder ohne `.service`, Aliase erlaubt, Daten spätestens mit dem nächsten vollen Inventar); beim Ignorieren (`:292-300`) Hinweis „Glob-Muster wie `foo@*` erlaubt“. `setCsvStr` entfernt Dubletten (doppelte Namen ergäben doppelte Keys im `{#each … (s.name)}` von `SecServices`). Test zuerst rot in der bestehenden `CheckConfigFields.test.ts`: Hinweise erscheinen je Modus; doppelte Einträge werden einmal gespeichert.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/monitoring/CheckConfigFields.test.ts
Doku: keine (intern; sichtbar mit T8)
Abhängt von: T6

### T8 — Doku und CHANGELOG  [x]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/agent.html, docs/en/developer/agent.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, CHANGELOG.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @54c5b5b2 2026-10-16T17:21:32+02:00
Review: approve (.ah-out/review/monitoring-services/T8.verdict.json)
Änderung: Admin-Doku DE+EN: Tabellenzeile `service_process` (`monitoring.html:46`) und Standard-Template (`:162`): `auto` meldet failed und enabled-aber-inaktive Units, nicht aber regulär beendete oneshot-, per Condition übersprungene oder per Timer/Socket gestartete Dienste; `ignore` mit Glob; Listen-Modus ohne `--services` am Agent, Namen mit/ohne `.service`, Aliase, Daten spätestens mit dem nächsten vollen Inventar (≤ 1 h). Entwickler-Doku DE+EN: Report-Felder `systemd.counts`, `systemd.error`, `alias_of`, sortiertes Inventar, gefiltertes `enabled_inactive` (`agent.html:101`, `:112`; `monitoring.html:112`, `:122`). CHANGELOG unter `### Fixed`.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/admin/monitoring.html + docs/en/admin/monitoring.html · docs/developer/agent.html + docs/en/developer/agent.html · docs/developer/monitoring.html + docs/en/developer/monitoring.html · CHANGELOG.md (Fixed)
Abhängt von: T5, T6, T7
