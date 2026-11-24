# kern-agent-21 — Ein Seam-Typ für die Kommandos der Monitor-Collectoren

Roadmap: R-0703 (REF, Code-Audit 2026-10-21). Umfang nach Kevins Wort vom 2026-11-24: Schritt 1, nur das
Paket `monitor`.

## Problem / Motivation

Sieben Collectoren in `apps/agent/internal/monitor` führen je ein eigenes, anonymes Struct als Testnaht für ein
externes Kommando: `dockerCLI` (`plugins.go:48`), `pveshCLI` (`plugins.go:332`), `zpoolCLI` (`plugins.go:832`),
`smartctlCLI` (`smart.go:65`), `systemCLI` (`system_linux.go:40`), `journalCLI` (`servicelogs_linux.go:33`) und
`freebsdCalls` (`pkgaudit.go:28`). Alle tragen `lookPath`, aber ihr `run` hat drei verschiedene Signaturen
(`(ctx, args…)`, `(ctx, name, args…)`, `(ctx, timeout, name, args…)`), und dazu kommen die Wrapper `runDocker`,
`runPvesh` und `runZpool`, die nur Name und Timeout einsetzen. Wer einen Collector testet oder einen neuen schreibt,
muss jedes Mal neu nachsehen, welche Form gerade gilt.

## Ziel & Nicht-Ziele

Ziel: ein benannter Typ `command` im Paket `monitor` mit `lookPath` und einem `run` in der Form des einen
Aufrufpunkts `runTimedEnv` (`ctx, timeout, env, name, args…`). Die sieben Nähte verwenden ihn: entweder ist die
Naht direkt ein `command`, oder sie bettet ihn ein, wenn sie zusätzliche Felder hat (`systemCLI.now`,
`pveshCLI.hostname`/`corosyncConf`). Die Collectoren geben Name und Timeout beim Aufruf selbst an, die Wrapper
`runDocker`, `runPvesh` und `runZpool` entfallen. Das Verhalten ändert sich nicht: dieselben Kommandos, Timeouts und
Allowlist-Prüfungen.

Nicht-Ziele (Kevin 2026-11-24):
- andere Pakete (`frpc`, `probe`, `discovery`, `cmd`): kommen in eine eigene, zurückgestellte Zeile;
- die Overrides `ADMINHELPER_*_DIR`: sie wirken seit R-1645/R-1655 nur noch in Testbinaries;
- `slog.SetDefault` in `internal/logging`: richtig für den Einstiegspunkt eines Binaries;
- `t.Parallel`: geht erst, wenn die Nähte keine Paketvariablen mehr sind, und das ist kein Ziel dieses Schritts;
- `hostFactsCalls` (`hostfacts.go:28`) und `updatesCalls` (`updates.go:28`): sie haben kein `lookPath`/`run`-Paar
  derselben Art. `updatesCalls.run` hat schon die Zielform.
- `runTimed` und `runWithTimeout` bleiben als Einzeiler für die Aufrufe ohne Naht (Dienste unter Windows und
  FreeBSD, `systemctl`), damit die plattformgebundenen Dateien unberührt bleiben.

## Betroffene Komponenten & Dateien

Nur `apps/agent/internal/monitor`:
- `allowlist.go`: Typ `command` neben `runTimedEnv`.
- `plugins.go`, `smart.go`, `system_linux.go`, `servicelogs_linux.go`, `pkgaudit.go`, `updates_linux.go`: die
  Aufrufer.
- Die Tests, die die Nähte stubben: `plugins_test.go`, `smart_test.go`, `report_test.go`,
  `report_golden_test.go`, `system_linux_test.go`, `servicelogs_linux_test.go`, `pkgaudit_test.go`,
  `system_freebsd_test.go`.

## Datenmodell / API / Migrationen

Keine. Wire-Format des Reports unverändert: die Golden-Dateien unter `testdata/report/` aus kern-agent-20 bleiben
byte-gleich und sind der Beweis.

## Externe Integrationen

Keine.

## Trade-offs & Alternativen

- **Interface `Runner` statt Funktionsfeld:** Das Roadmap-Zitat schlägt ein Interface vor. Die Tests stubben heute
  mit Closures; ein Interface verlangt je Stub einen Typ. Empfehlung: Funktionsfeld in der Form des Interfaces
  (`ctx, timeout, env, name, args`), damit ein späterer Schritt es ohne neue Aufrufform zum Interface machen kann.
- **Struct-Felder je Collector statt Paketvariablen:** Das wäre der volle Umbau, gehört aber nicht in Schritt 1.

## Risiken & Rollback

- Ein falscher Timeout oder Name beim Umstellen eines Aufrufs: Die vorhandenen Collector-Tests prüfen Name und
  Argumente, die Golden-Tests die Report-Form. Jede Task fährt die Paket-Suite und zusätzlich
  `GOOS=windows go vet ./...` und `GOOS=freebsd go vet ./...` (die FreeBSD-Tests in `pkgaudit_test.go` und
  `system_freebsd_test.go` laufen nur quer gebaut).
- Rollback: `git revert` je Task.

## Doku-Impact

Keine (internes Refactoring ohne dokumentiertes Verhalten), kein CHANGELOG-Eintrag.

## Offene Fragen

Keine. Kevin hat den Umfang am 2026-11-24 entschieden.
