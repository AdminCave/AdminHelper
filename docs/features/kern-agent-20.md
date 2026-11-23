# kern-agent-20 — der Agent-Report als typisierte Structs

Roadmap: R-0688 (REF, Code-Audit 2026-10-21, AGT-7).

## Problem / Motivation
Der Agent baut seinen Monitoring-Report (`report_version` 4, `apps/agent/internal/monitor/report.go:61`) aus
verschachtelten `map[string]any`; rund 110 Stellen in 22 Quelldateien des Pakets schreiben und lesen sie über
String-Schlüssel. Die Leser setzen Typen voraus, ohne sie zu prüfen: `services_linux.go:61-62,72,85`
(`health["enabled_inactive"].([]string)`, `health["all_services"].([]ServiceEntry)`) panicken, sobald ein Schreiber
den Typ ändert; `inventory.go:96`, `loadgate.go:115` und `processes.go:142` lesen Blöcke anderer Collectoren per
Schlüssel. Ein Tippfehler im Schlüssel fällt weder dem Compiler noch einem Test auf, und was der Monitoring-Dienst
empfängt, steht an keiner Stelle als Vertrag.

## Ziel & Nicht-Ziele
- **Ziel:** Jeder Block des Reports ist ein Go-Struct mit `json`-Tags; die Collectoren liefern diese Structs, die
  Leser greifen auf Felder zu, keine ungeprüfte Type-Assertion bleibt. `BuildReport` liefert ein `Report`-Struct.
- **Vertrag zuerst:** Golden-JSON-Tests je Block (`testdata/report/*.json`) halten die heutige Ausgabe fest, bevor
  ein Block umgestellt wird; sie bleiben bei jeder Umstellung unverändert grün. Verglichen wird das dekodierte JSON
  (Schlüssel, Werte, `null` gegen `[]`, fehlender Schlüssel gegen leeren), nicht die Bytes.
- **Gleiches Wire-Format:** Dieselben Schlüssel, Typen und Auslassungen wie heute; `report_version` bleibt 4. Der
  Monitoring-Dienst merkt nichts.
- **Nicht-Ziele:** keine neuen Felder, keine Änderung am Push, an Plan, Probes oder Discovery (ihre Pakete liefern
  schon Structs), keine Server- oder Monitoring-Änderung. Die Aufteilung des Pakets `monitor` (Collectoren getrennt
  von Push und Init) wird eine eigene Roadmap-Zeile: sie setzt die Typen voraus, bewegt fast jede Datei und soll für
  sich zurücknehmbar sein.

## Betroffene Komponenten & Dateien
Nur `apps/agent/internal/monitor/` (plus `monitor.go`, Aufrufer von `BuildReport`):
- Ressourcen, Host, Prozesse, Self: `collector.go`, `hostfacts.go`, `processes.go`, `loadgate.go`,
  `selfmeasure.go`, `report.go` (`collectResources`).
- Dienste: `services_linux.go`, `services_freebsd.go`, `services_windows.go`, `rcservice.go`, `scquery.go`,
  `servicelogs_*.go`, `inventory.go`, `report.go` (`failedUnits`, `serviceLogUnits`, `collectServiceLogs`).
- Systemzustand: `system_linux.go`, `system_freebsd.go`, `system_windows.go`, `system_other.go`, `updates.go`,
  `pkgaudit.go`.
- Plugins: `plugins.go` (Docker, Proxmox, ZFS), `smart.go`.
- Die Tests der Dateien (rund 210 Map-Zugriffe in 21 Testdateien) lesen danach Felder.

## Datenmodell / API / Migrationen
Keine. Das JSON des Reports bleibt gleich; die Golden-Dateien sind der Beleg.

## Externe Integrationen
Keine neuen. `encoding/json`: `omitempty` lässt bei Slices und Maps auch leere (nicht nur nil) weg, ein nil-Slice
ohne `omitempty` wird `null` (https://pkg.go.dev/encoding/json#Marshal); jeder Block wählt die Tags so, dass die
Golden-Datei gleich bleibt.

## Trade-offs & Alternativen
- **Ein großer Umbau** wäre kürzer, aber nicht reviewbar und nicht teilweise zurücknehmbar. **Empfehlung:** je Block
  eine Task gegen den unveränderten Vertrag.
- **Golden über den ganzen Report** scheitert an gopsutil-Werten des Hosts; die Blöcke haben Seams
  (`pluginCollectors`, `runDocker`, `runPvesh`, `runZpool`, `serviceHealthCollector`, `systemStateCollector`) oder
  reine Assemble-Funktionen. Der Report als Ganzes bekommt einen Test seiner Schlüsselmenge mit gestubbten
  Collectoren.
- **Paket-Split jetzt mitnehmen:** abgelehnt (siehe Nicht-Ziele).

## Risiken & Rollback
- **Stille Wire-Drift** (ein Feld fällt weg, `null` statt `[]`, Zahl als String): die Golden-Tests fangen sie,
  solange sie vor der Umstellung entstehen und danach unverändert bleiben; der Prüfer sieht jede Änderung unter
  `testdata/report/` als Befund.
- **Plattform-Code:** Windows- und FreeBSD-Dateien baut die Dev-Box nur quer (`GOOS=windows|freebsd go vet`); die
  Windows-Tests laufen im PR-Job `agent-windows`.
- Rollback: jede Task ist ein Commit, einzeln per `git revert` zurücknehmbar.

## Doku-Impact
`docs/developer/agent.html:121` (DE+EN) sagt, alle Collectoren lieferten `map[string]any`; nach dem Umbau nennt die
Stelle die Structs und den Golden-Vertrag. Kein CHANGELOG-Eintrag (kein Nutzer-Verhalten).

## Offene Fragen
Keine.
