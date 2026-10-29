<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Agent: ein Kontext und ein Budget je Lauf, Stopp mitten im Zyklus, frpc-Sperre, Log-Datei unter Windows

Stand des Codes: `origin/main@b1432223`. Alle `datei:zeile` beziehen sich auf diesen Stand, Pfade ohne Präfix liegen
unter `apps/agent/`. Ledger: `tasks/agent-run-ctx.md`. Roadmap R-0638, R-0640, R-0406 (Paket agent-run-ctx), dazu
R-0641, R-0639 und R-0619 (Kevin 2026-10-21).

Kernidee: Ein Lauf hat einen Kontext mit Gesamtbudget. Er reicht bis in das Warten auf Sperren, die HTTP-Anfragen von
Erneuerung und Sync, jeden `systemctl`-Aufruf des frpc-Pfads und jeden Werkzeug-Aufruf der Collector. Ein Signal oder
ein Dienst-Stopp bricht ihn ab, auch mitten in einem Zyklus.

## Problem / Motivation

1. **Kein Gesamtbudget je Lauf (R-0638).** `runOnce` (`cmd/adminhelper-agent/run.go:86-105`) ruft
   `maybeRenewIdentity()` ohne Kontext (`:90`), `frpc.Sync()` ohne Kontext (`:92`) und erst danach `monitor.Push(ctx)`
   (`:98`). Die Einzeldeckel summieren sich: Warten auf die Identitäts-Sperre bis 60 s (`internal/enroll/lock.go:24`),
   Erneuerung 30 s (`run.go:119`), Sync zwei Anfragen zu je 30 s (`internal/frpc/sync.go:61`, `:71`, `:110`),
   Collector-Aufrufe zu 10–30 s (`internal/monitor/plugins.go:22`, `:29`; `smart.go:66`, `:140` mit 30 s je Gerät;
   `updates_linux.go:19`), Push 15 s + 10 s Backoff + 15 s (`report.go:105`, `:152`). Die `systemctl`-Aufrufe des
   frpc-Pfads haben gar keinen Deckel (`internal/frpc/platform_linux.go:26`, `:32`, `:35`, `:43`, `:48`, `:53`) und
   laufen vor dem Push: `frpcStuck` (`sync.go:99`, `:151-156`) fragt bei jeder Änderung `systemctl is-active`. Die Unit
   beendet den Lauf nach 270 s (`systemd/adminhelper-agent.service:13`, `internal/service/service_linux.go:60`). Hängen
   systemd oder D-Bus, endet der Lauf so ohne Push, und der Host meldet nichts.
   Dazu hält ein Deckel der Collector nicht, wenn das Werkzeug einen Kindprozess startet, der stdout offen hält:
   `exec.Cmd.Output` wartet dann auf dessen Ende. Probe an `origin/main@b1432223` mit dem Wortlaut von `runTimed`
   (`plugins.go:55-63`), Go 1.26.9: `runTimed(200ms, "sh", "-c", "sleep 4 & sleep 4")` kehrt nach 4,0 s mit
   `context deadline exceeded` zurück, dreimal identisch.

2. **Ein Signal greift nicht während eines Zyklus (R-0640).** `runLoop` (`run.go:53-78`) registriert SIGINT/SIGTERM
   mit `signal.Notify` (`:57`), was den Standardabbruch abschaltet („Notify disables the default behavior for a given
   set of asynchronous signals“, pkg.go.dev/os/signal). `runOnce` läuft in derselben Goroutine wie das `select`
   (`:67`, `:72`); der Kontext (`:61`) wird erst beim `return` abgebrochen, nie während eines Zyklus. Der Kommentar
   `:59-60` behauptet das Gegenteil. Im Windows-Dienst (`run_windows.go:25-73`) läuft der Zyklus zwar in einer eigenen
   Goroutine (`:47-50`), `cancel` (`:68`) erreicht aber nur den Push (`report.go:168-172`, `:178-179`), und `Execute`
   kehrt sofort zurück (`:69`). Danach endet der Prozess („the service will exit once Execute completes“,
   pkg.go.dev/golang.org/x/sys/windows/svc, `Handler`), auch mitten in einem Schreibvorgang des Zyklus.

3. **Das Warten auf die Identitäts-Sperre kennt keinen Kontext (R-0406).** `waitForLock` (`lock.go:63-77`) versucht
   es bis `identityLockWait` (60 s) mit `time.Sleep` (`:74`). `MaybeRenew` (`renew.go:99`, `:103`) und
   `runEnrollment` (`internal/provision/provision.go:309`) geben keinen Kontext mit. Ein Dienst-Stopp während des
   Wartens wartet bis zu 60 s.

4. **frpc-Zustand ohne Sperre, Timer aus dem Sync heraus (R-0641).** `applyConfig` (`sync.go:174-226`) schreibt über
   den festen Namen `frpc.toml.tmp` (`:202-207`), danach `.started-hash` (`:259-275`) und `.config-hash`; `Sync` kann
   vorher `admin.conf` erneuern (`:130`, `internal/frpc/admin.go:57`). Der Timer-Lauf (`frpc.Sync`) und die
   Provisionierung (`frpc.Apply`, `internal/frpc/apply.go:108-136`) können das gleichzeitig tun; `R-0384` sperrt nur die
   Identität. `enableFrpcService` schaltet neben `frpc.service` auch `adminhelper-agent.timer` ein
   (`platform_linux.go:35`) und läuft auch im Sync eines Dauerbetriebs `run`: Schleife und Timer laufen dann
   nebeneinander. `monitor.Init` schaltet den Timer ebenfalls ein (`internal/monitor/monitor.go:141`,
   `internal/monitor/platform_linux.go:13`).

5. **`--ca-fp`: der Erstkontakt prüft keinen Hostnamen, alle Folgeaufrufe schon (R-0639).** `NewCAFingerprint`
   (`internal/httpclient/httpclient.go:121-144`) prüft bewusst keinen Hostnamen („Hostname is intentionally not
   enforced“, `:126-128`; „No DNSName on purpose“, `:184-185`). Danach pinnt die Provisionierung den Anker als
   CA-Datei (`provision.go:126`), und alle Folgeaufrufe gehen über `httpclient.New`/`NewMTLS` mit der normalen
   Prüfung samt Hostname: Enrollment (`provision.go:292`), Test-Push in `monitor.Init` (`monitor.go:127`), Sync und
   Push (`internal/enroll/client.go:47`, `:49`). Wer über eine IP oder einen Alias provisioniert, den das Gateway-Leaf
   nicht nennt, bekommt: Token eingelöst, „Enrollment uebersprungen“ (`provision.go:142-143`), „OK: Provisioning
   abgeschlossen.“ (`:204`), danach scheitert jeder Lauf mit einem x509-Hostnamen-Fehler. Der Desktop baut den Befehl
   mit seiner eigenen Server-URL (`apps/desktop/ui/src/components/infra/tabs/ProvisioningTab.svelte:76`, `:85`); ein
   Desktop, der über eine IP verbunden ist, erzeugt genau diesen Fall. `TestCAFingerprintAcceptsChainToPinnedCA`
   (`internal/httpclient/cafp_test.go:95-110`) hält fest, dass ein Leaf ohne den Verbindungshost angenommen wird.

6. **Windows-Dienst ohne `agent.log` (R-0619).** `logging.Init` schreibt über `io.MultiWriter(os.Stdout, lumberjack)`
   (`internal/logging/logging.go:57`). „If a listed writer returns an error, that overall write operation stops and
   returns the error; it does not continue down the list.“ (pkg.go.dev/io, `MultiWriter`). Ein Dienst hat kein
   stdout: „If an application does not have associated standard handles, such as a service running on an interactive
   desktop, and has not redirected them, the return value is NULL.“ (learn.microsoft.com, `GetStdHandle`). Go legt
   `os.Stdout` trotzdem als `*File` mit Handle 0 an (`newFileFromNewFile` prüft nur `InvalidHandle`,
   `src/os/file_windows.go`, Go 1.26.9); ein Write darauf scheitert, die Datei bekommt nichts. Probe (Linux, ein
   geschlossenes `*os.File` als stdout, slog wie `Init`): 0 Bytes im Datei-Writer, dreimal identisch. Unter dem SCM
   nicht nachgestellt (Pool ohne Windows-Vorlage). Die Doku verspricht die Datei auch unter Windows
   (`docs/admin/agent-deployment.html:198-201`).

## Ziel & Nicht-Ziele

Ziel:
- `runOnce` hat ein Gesamtbudget von 240 s (30 s unter `TimeoutStartSec=270`) mit Phasen: Erneuerung höchstens 60 s,
  FRP-Sync höchstens 60 s, die Erhebung des Reports bis 45 s vor dem Ende des Budgets, der Push in diesen 45 s
  (`PushReport` braucht höchstens 15 + 10 + 15 s). Ein hängender Schritt kostet seine Phase, nicht den Report. Ein
  Lauf ohne Hänger ändert nichts an Ablauf und Reihenfolge.
- Der Kontext reicht in `waitForLock`, die Anfrage der Erneuerung (`Submit`), die beiden Anfragen des Sync, jeden
  `systemctl`-Aufruf des frpc-Pfads (eigener Deckel 15 s, wie `pluginTimeout`) und jeden Werkzeug-Aufruf der
  Collector (`runTimed`, `runWithTimeout`, `runTimedEnv`). Ein Werkzeug-Aufruf endet auch, wenn ein Enkelprozess
  stdout offen hält (`exec.Cmd.WaitDelay`).
- SIGINT/SIGTERM im Dauerbetrieb und Stop/Shutdown des Windows-Dienstes brechen einen laufenden Zyklus ab. Beendet
  wird, sobald der Zyklus zurück ist, spätestens nach 10 s. Ein zweites Ctrl-C im Dauerbetrieb beendet sofort.
- `frpc.Sync`, `frpc.Apply`, `frpc.ApplyWithoutBundle` und `frpc.WriteSyncConfig` ändern den frpc-Zustand nur unter
  einer exklusiven Sperre `frpc.lock` im FRP-Verzeichnis. `adminhelper-agent.timer` schalten nur `provision`,
  `monitor init` und `service install` ein, nie ein Lauf.
- Unter Windows bekommt `agent.log` jede Zeile, auch wenn stdout nicht schreibbar ist.
- (Offene Frage 1) `--ca-fp` prüft den Hostnamen schon im Erstkontakt, bevor der Token den Host verlässt.

Nicht-Ziele (YAGNI):
- `TimeoutStartSec=270` und das Intervall bleiben (Unit und `service_linux.go:60`).
- Keine Änderung an Feldern oder Fehlercodes des Reports: Ein Aufruf, den das Budget beendet, meldet sich wie ein
  Timeout (`timeout`, „timed out after 15s“); ein abgebrochener Lauf pusht ohnehin nicht. Der Vertrag mit dem
  Monitoring-Dienst bleibt.
- gopsutil-Aufrufe (`disk.Usage`, Sensoren, Host-Fakten) bekommen keinen Kontext: Ein `statfs` auf einem hängenden
  NFS-Mount ist im Kernel nicht abbrechbar (Risiken).
- `provision`, `monitor init`, `service install/uninstall`, `frpc sync` und `monitor push` von Hand bekommen kein
  Budget, nur die Deckel je Aufruf; Ctrl-C beendet sie wie bisher sofort.
- `frpc.toml.tmp` bleibt ein fester Name (Trade-off 4).
- Ausgabe von `systemctl` in Fehlertexten und ein gemeinsamer systemd-Helfer für `service_linux.go`: R-0705, nicht in
  diesem Ledger (T6 legt den Helfer im frpc-Pfad so an, dass R-0705 ihn erweitern kann).
- `--insecure` zeigt dasselbe Muster wie `--ca-fp` (TOFU-Pin der Kette, Folgeaufrufe prüfen den Hostnamen,
  `provision.go:128`, `:241-260`); nicht Teil von R-0639 (offene Frage 3).
- Kein Nachweis unter einem echten SCM (keine Windows-VM im Pool); Windows belegen die CI-Jobs, der Rest gehört zu
  R-0541.
- R-0576 (RPM `%post`) gehört nicht dazu.

## Betroffene Komponenten & Dateien

Alle Tasks: Komponente `agent` (`verify.sh agent`). Pfade relativ zum Repo.

| Task | Zeile | Dateien |
|---|---|---|
| T1 | R-0619 | `apps/agent/internal/logging/logging.go`, `logging_test.go`, `logging_linux_test.go` (neu), `CHANGELOG.md` |
| T2 | R-0640 | `apps/agent/cmd/adminhelper-agent/run.go`, `run_windows.go`, `run_test.go` (neu), `run_signal_test.go` (neu), `run_windows_test.go` (neu), `CHANGELOG.md` |
| T3 | R-0406 | `apps/agent/internal/enroll/lock.go`, `renew.go`, `lock_test.go`, `renew_test.go`, `enroll_windows_test.go`, `apps/agent/internal/provision/provision.go`, `provision_test.go`, `apps/agent/cmd/adminhelper-agent/run.go` |
| T4 | R-0638 | `apps/agent/internal/enroll/enroll.go`, `renew.go`, `enroll_test.go`, `renew_test.go`, `apps/agent/internal/provision/provision.go` |
| T5 | R-0638 | `apps/agent/internal/frpc/sync.go`, `http.go`, `sync_flow_test.go`, `apply_test.go`, `admin_test.go`, `sync_windows_test.go`, `apps/agent/cmd/adminhelper-agent/run.go`, `main.go` |
| T6 | R-0638 | `apps/agent/internal/frpc/platform_linux.go`, `platform_windows.go`, `sync.go`, `apply.go`, `sync_flow_test.go`, `apply_test.go`, `platform_linux_test.go` (neu), `docs/developer/agent.html`, `docs/en/developer/agent.html` |
| T7 | R-0641 | `apps/agent/internal/enroll/lock.go`, `apps/agent/internal/frpc/sync.go`, `apply.go`, `lock_test.go` (neu, frpc), `docs/developer/agent.html`, `docs/en/developer/agent.html`, `CHANGELOG.md` |
| T8 | R-0641 | `apps/agent/internal/frpc/platform_linux.go`, `platform_linux_test.go`, `apps/agent/internal/monitor/monitor.go`, `internal/monitor/platform_linux.go` (weg), `internal/monitor/platform_windows.go` (weg), `apps/agent/internal/service/service_linux.go`, `service_windows.go`, `apps/agent/internal/provision/provision.go`, `provision_test.go`, `apps/agent/cmd/adminhelper-agent/main.go`, `docs/developer/agent.html`, `docs/en/developer/agent.html`, `CHANGELOG.md` |
| T9 | R-0638 | `apps/agent/internal/monitor/plugins.go`, `plugins_test.go`, `report.go`, `report_test.go`, `monitor.go`, `smart.go`, `services_linux.go`, `services_windows.go`, `system_linux.go` |
| T10 | R-0638 | `apps/agent/internal/monitor/smart.go`, `smart_test.go`, `report.go`, `report_test.go` |
| T11 | R-0638 | `apps/agent/internal/monitor/services_linux.go`, `services_windows.go`, `services_linux_test.go`, `report.go`, `report_test.go` |
| T12 | R-0638 | `apps/agent/internal/monitor/system_linux.go`, `system_other.go`, `updates_linux.go`, `system_linux_test.go`, `updates_linux_test.go`, `report.go`, `report_test.go` |
| T13 | R-0638 | `apps/agent/cmd/adminhelper-agent/run.go`, `run_test.go`, `apps/agent/internal/monitor/monitor.go`, `report_test.go`, `docs/developer/agent.html`, `docs/en/developer/agent.html`, `CHANGELOG.md` |
| T14 | R-0639 | `apps/agent/internal/httpclient/httpclient.go`, `cafp_test.go`, `apps/agent/internal/provision/provision.go`, `provision_test.go`, `docs/admin/agent-deployment.html`, `docs/en/admin/agent-deployment.html`, `CHANGELOG.md` |

Risikopfade (`scripts/dev/review-risk.txt`): `internal/enroll/*`, `internal/frpc/*`, `internal/provision/*`,
`internal/httpclient/httpclient.go`. T3–T8 und T14 bekommen zusätzlich `security`. Die Sperre bleibt deshalb im Paket
`enroll` (Trade-off 5).

## Datenmodell / API / Migrationen

Keine Server-Route, kein Schema, keine Migration, kein Report-Feld. Die CLI-Flags bleiben (`box_cli_test.go` pinnt die
Aufrufe der Box-Skripte). Geänderte Go-Signaturen innerhalb des Moduls (keine Nutzer außerhalb von `apps/agent`):
`enroll.LockIdentity(ctx, dir)`, `enroll.MaybeRenew(ctx, …)`, `enroll.Renew(ctx, …)`, `enroll.Submit(ctx, …)`, neu
`enroll.LockFile(ctx, path, wait)`; `frpc.Sync(ctx)`; neu `service.EnableTimer()`; `monitor.Push(ctx)` bleibt,
`monitor.BuildReport(names)` bleibt; T14 `httpclient.NewCAFingerprint(fp, host, timeout)`. Neu auf dem Host ist die
leere Sperrdatei `frpc.lock` neben `frpc.toml` (Linux `/etc/frp/frpc.lock`, Windows
`%ProgramData%\AdminHelper\frp\frpc.lock`). Kein Vertrags-Drift zu Server, Web oder Desktop.

## Externe Integrationen

Alles gelesen am 2026-10-22:
- `os/signal.NotifyContext` (pkg.go.dev/os/signal): der Kontext endet, wenn ein gelistetes Signal kommt, `stop`
  aufgerufen wird oder der Eltern-Kontext endet; „The stop function unregisters the signal behavior, which, like
  signal.Reset, may restore the default behavior“.
- `os/exec` (pkg.go.dev/os/exec): `CommandContext` „sets the command's Cancel function to invoke the Kill method on its
  Process, and leaves its WaitDelay unset“; `WaitDelay`: „The WaitDelay timer starts when either the associated
  Context is done or a call to Wait observes that the child process has exited, whichever occurs first. When the
  delay has elapsed, the command shuts down the child process and/or its I/O pipes.“
- `io.MultiWriter` und `GetStdHandle`: Zitate unter Problem 6.
- `golang.org/x/sys/windows/svc`: `Handler.Execute` – „the service will exit once Execute completes“; `Status.WaitHint`
  – „estimated time required for a pending operation, in milliseconds“.
- `crypto/x509` (pkg.go.dev/crypto/x509): `VerifyOptions.DNSName` – „if set, is checked against the leaf certificate
  with Certificate.VerifyHostname or the platform verifier“; `VerifyHostname` – „IP addresses can be optionally
  enclosed in square brackets and are checked against the IPAddresses field.“ Mit eigenem `Roots` prüft Go selbst,
  nicht die Plattform.
- systemd: nur die eigene Unit (`TimeoutStartSec`), keine neue systemd-Funktion.

## Trade-offs & Alternativen

1. **Budget und Phasen (T13).** (a) Reihenfolge bleibt (Erneuerung, Sync, Erhebung, Push), Phasen-Deckel 60/60 s,
   Push-Reserve 45 s am Ende des 240-s-Budgets — **Empfehlung**: Der Push kommt immer, der Sync bekommt immer seine
   60 s, die Erhebung im schlechtesten Fall 75 s, sonst rund 195 s. (b) Push zuerst, danach Erneuerung und Sync mit dem
   Rest: Ein langsamer SMART-Lauf verzögerte dann die Tunnel-Änderungen, und eine fällige Erneuerung käme erst nach dem
   Push. (c) Nur ein Gesamtbudget ohne Phasen: Ein hängender Sync äße die Erhebung auf, und der Report meldete jedes
   Plugin als `timeout`, was im Monitoring falsche Alarme auslöst.
2. **Kontext bis in die Collector (T9–T12) statt eines Kontexts auf Paketebene.** Ein Kontext in einer Paketvariablen
   spart die Signaturänderungen, ist aber versteckter globaler Zustand (Go-Doku: Kontexte explizit übergeben). Die
   Aufteilung nach Collector-Familie hält die Tasks klein; bis zur letzten Familie rufen die übrigen das Blatt mit
   `context.Background()` wie heute, danach steht im Paket `monitor` kein `context.Background()` mehr außer in
   `BuildReport` und `Init`.
3. **`is-active` ohne Antwort (T6).** Heute heißt jeder Fehler „nicht aktiv“ (`platform_linux.go:53`). Mit einem
   Deckel entstünde ein neuer Ausgang: Ein Timeout gälte als „frpc steht“, und der Sync erneuerte die Admin-API und
   startete frpc neu. Deshalb liefern `isActive`/`isDown` einen Fehler, wenn `systemctl` nicht antwortet (Timeout,
   Start gescheitert), und der Sync bricht ab, ohne etwas zu ändern. Ein Exit-Status ungleich 0 bleibt „nicht aktiv“.
4. **Fester Name `frpc.toml.tmp` statt `CreateTemp` (T7).** Mit der Sperre gibt es keinen zweiten Schreiber.
   `CreateTemp` ließe nach jedem Absturz eine weitere Datei mit dem frps-Token liegen; der feste Name wird beim
   nächsten Lauf überschrieben. Die Zeile nennt `CreateTemp` als Vorschlag; die Sperre deckt denselben Fall.
5. **Wo die Sperre lebt (T7).** (a) `enroll.LockFile(ctx, path, wait)` neben `LockIdentity`, das sie nutzt —
   **Empfehlung**: Plattformcode und Eigentümer-Prüfung unter Windows bleiben, wo sie sind, im Risikopfad
   `internal/enroll/*`, und kein Test zieht um. (b) Ein neues Paket `internal/filelock`: stünde nicht auf
   `review-risk.txt` (Harness), `TestLockOwnerAllowed` müsste umziehen.
6. **Welche Wege sperren (T7).** Die Sperrdatei entsteht nur in einem Verzeichnis, das derselbe Aufruf vorher
   gesichert hat (heutige Regel, `sync.go:137-147`). Deshalb nimmt `Sync` sie erst auf dem Änderungsweg nach
   `secureFrpDir` und prüft unter der Sperre nicht neu: Was er anwendet, ist die vom Server geprüfte Config
   (`sync.go:120-122`), und ein zweites Anwenden ist harmlos. Ein Lauf ohne Änderung sperrt nichts und sichert nichts
   (wie heute). Die zwei Sperren verschachteln sich nie: `runEnrollment` gibt die Identitäts-Sperre vor `frpc.Apply`
   frei, die Erneuerung vor dem Sync.
7. **Wartezeit beim Stopp (T2).** 10 s: Nach diesem Paket endet jeder blockierende Aufruf mit dem Kontext (Kill plus
   `WaitDelay` 2 s). Ein Zyklus, der trotzdem nicht zurückkommt, hält den Stopp nicht länger auf; der Windows-Dienst
   meldet `StopPending` mit dieser Zeit als `WaitHint`.
8. **Timer (T8).** `service.EnableTimer()` an einer Stelle, aufgerufen von `provision` (immer, am Ende),
   `monitor init` und `service install`. Alternative: nur die Zeile in `enableFrpcService` streichen; dann schaltete
   eine Provisionierung ohne Monitor nichts mehr ein, und mit Monitor zweimal.

## Risiken & Rollback

- Ein Budget kann einen Lauf abschneiden, der heute nach 200 s noch fertig würde (viele Platten mit SMART): Die
  Erhebung endet dann bei Budget − 45 s, die übrigen Plugins melden `timeout`. Heute endete derselbe Lauf bei 270 s
  ohne Report.
- Ein `statfs` auf einem hängenden Netz-Mount (gopsutil `disk.Usage`) hält die Erhebung weiter an; der Kontext hilft
  dort nicht (Nicht-Ziel). Die Unit beendet den Lauf dann wie heute nach 270 s.
- `WaitDelay` (2 s) schließt nach Ende des Werkzeugs auch die Pipes eines Enkels: Dessen späte Ausgabe fehlt. Heute
  wartete der Aufruf stattdessen auf den Enkel.
- Die neue Sperre kann eine Provisionierung bis 60 s warten lassen, wenn gerade ein Sync läuft (Budget des Syncs
  60 s); läuft die Wartezeit ab, endet `provision` mit einem Fehler, der die Sperrdatei nennt, nach dem Einlösen des
  Tokens (wie heute ein Schreibfehler). Ein Timer-Lauf, der warten müsste, bricht nach seinem Sync-Budget ab, der
  nächste Lauf holt den Abgleich nach.
- Windows: Der Dienst-Stopp wartet jetzt bis 10 s statt sofort zu enden. Unter einem echten SCM nicht belegt (R-0541).
- Rollback: jede Task ist ein eigener Commit ohne Datenänderung; Revert genügt. Eine zurückbleibende `frpc.lock` ist
  leer und stört keinen älteren Agent.

## Doku-Impact

- `CHANGELOG.md` (umlautfrei): T1 (Fixed, `agent.log` unter Windows), T2 (Fixed, Stopp im Zyklus), T7 (Fixed, Sperre),
  T8 (Changed, Timer), T13 (Fixed, Budget und Abbruch bis in Sperre, Sync und Werkzeuge), T14 (Changed).
- `docs/developer/agent.html` + `docs/en/developer/agent.html`: T6 (FRP-Abgleich: Deckel je `systemctl`-Aufruf, Abbruch
  bei Status ohne Antwort), T7 (Sperre), T8 (Zeile `enableMonitorService()` → `service.EnableTimer()`), T13
  (Push-Verhalten: Budget und Reserve statt „Den ganzen Lauf begrenzt unter Linux `TimeoutStartSec=270`“, `:132`).
- `docs/admin/agent-deployment.html` + EN: nur T14 (`--ca-fp`-Absatz, `:187` bzw. EN `:186`).
- T3, T4, T5, T9–T12: keine (intern).

## Offene Fragen

1. **R-0639 (T14, `[?]`): Soll `provision --ca-fp` abbrechen, bevor der Token den Host verlässt, wenn das Zertifikat
   des Gateways den Host aus `--url` nicht nennt?** Optionen: (a) Abbruch mit einer Meldung, die den Host und die
   Namen des Zertifikats nennt und sagt, mit einem dieser Namen zu provisionieren oder die Adresse in `EXTRA_SANS` des
   Servers aufzunehmen; der Token bleibt gültig — **Empfehlung**: klein, fail-closed, und der Zustand danach
   funktioniert; heute endet derselbe Fall mit „OK“ und einem Host, der nie meldet. Trade-off: Wer heute über eine IP
   außerhalb der SANs provisioniert (auch über einen Befehl aus einem per IP verbundenen Desktop), bekommt jetzt einen
   Fehler statt eines scheinbaren Erfolgs. (b) Pin statt Hostname auch in allen Folgeaufrufen (Modell des Desktops):
   ändert das Vertrauensmodell der wiederkehrenden mTLS-Aufrufe (PKI), deutlich größer. (c) Nur warnen: der kaputte
   Zustand bliebe. Hängt nur T14 daran.
2. **Heavy: `scenario --agents 1 --tunnel` vor dem Merge (Multibox, ask-first).** Empfehlung: ja, ohne `--strict`;
   nur dieser Lauf zeigt `provision` mit `--ca-fp` über das IP-SAN (positiver Pfad von T14), die frpc-Sperre und die
   `systemctl`-Deckel unter echtem systemd mit einem Tunnel. Trade-off: ein Multibox-Lauf mehr vor dem Merge (Dauer
   nicht gemessen).
3. **`--insecure`** zeigt dasselbe Muster wie R-0639 (Nicht-Ziele). Vorschlag: eigene Roadmap-Zeile (Fund dieser
   Planung, bleibt `neu`), nach der Antwort auf Frage 1 im selben Sinn.
