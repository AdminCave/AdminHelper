<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Agent: eine Vertrauensquelle je Aufruf, PKI-Bundle-Pfad entfernt, Diagnose-Bericht als neue Datei, Server-Text der frpc.toml in Generator-Form — Task-Ledger
Status: erledigt · Branch: feature/agent-hardening · Review: pro Task
Spec: docs/features/agent-hardening.md (Härtung, Kevin 2026-10-22)
Heavy: linux-full + scenario --agents 1 --tunnel + windows — Agent-Paket im Stack (`run.sh integration`/`e2e`: `agent_monitoring`, `upgrade_path`, `desktop_e2e_connect_tunnel` mit echter Server-Ausgabe durch die neue Prüfung der frpc.toml); vor dem Merge der Multibox-Lauf `--agents 1 --tunnel` (ask-first, Kevin entscheidet), weil nur er die frpc.toml des Servers über `.deb`-Installation, Provisionierung über den Hop und den STCP-Datenpfad mit Visitor zeigt; `windows` ist der CI-Job `agent-windows` (`go test` unter Windows), weil sich `paths.go`, `WriteSyncConfig`, die Diagnose und `securedir_windows.go` auch unter Windows ändern
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Ziel: (1) `provision` und `monitor init` nehmen je Aufruf eine Vertrauensquelle; `--insecure` gilt nur für den Aufruf
selbst, wie `docs/admin/agent-deployment.html:188` es sagt, und `INSECURE=1` wird nie gespeichert. (2) Der ungenutzte
PKI-Bundle-Pfad und `frp/pki` entfallen. (3) `diagnostics` legt jeden Bericht als neue Datei an. (4) Der Agent wendet
eine frpc.toml des Servers nur in der Form an, die `generate_frpc_toml` schreibt; ein Server-Test hält Generator und
Prüfung über eine gemeinsame Fixture zusammen. Zeilenangaben: origin/main@b1432223; der builder greppt sie vor dem
Schreiben neu.

Für alle Tasks:
- Reihenfolge: T1 → T2 → T3 → T4 → T5 (T1/T4 teilen `provision.go`, T3–T5 `apply.go`/`apply_test.go`); T6 unabhängig;
  T7 → T9; T8 nach T7 und wartet auf Kevin.
- `apps/agent/internal/provision/*` und `apps/agent/internal/frpc/*` stehen auf `scripts/dev/review-risk.txt`: T1, T3,
  T4, T5, T7 und T8 bekommen zusätzlich `security`.
- Kein Test ruft `systemctl` (auch nicht beim Rot-Lauf auf HEAD): frpc über die Nähte aus `setupSyncTest`
  (`apps/agent/internal/frpc/sync_flow_test.go:36-56`), `provision.Run` mit `frp: null` über `applyWithoutBundle`
  (`apps/agent/internal/provision/provision.go:72-73`), `monitor.Init` über die Naht aus T2. `pushRetryDelay`
  (`apps/agent/internal/monitor/report.go:105`) setzt ein Test, der bis zum Push kommt, auf `time.Millisecond` wie
  `report_test.go:205-206`.
- Neue Code-Strings (Fehler, Log, Hilfetexte) englisch; bestehende deutsche Texte bleiben.
- Platzhalter: Adressen aus RFC 5737, Hosts unter `.example`; Token und Secrets als erkennbare Platzhalter.
- CHANGELOG umlautfrei, beschreibt das gewünschte Verhalten.
- Parallel geplant ist agent-run-ctx (Lauf-Kontext, frpc-Sperre, Timer-Aktivierung, `--ca-fp`-Erstkontakt); es
  berührt dieselben Dateien (`provision.go`, `monitor.go`, `sync.go`, `apply.go`, `paths.go`). Diffs hier so klein wie
  möglich halten, keine Signaturen ändern, die die Aufgabe nicht braucht.

### T1 — provision: `--cacert` mit `--insecure` ablehnen, blindes `--insecure` ohne Zertifikat bricht ab  [x]
Komponente: agent · Dateien: apps/agent/internal/provision/provision.go, apps/agent/internal/provision/provision_test.go, docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, CHANGELOG.md
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @fe6aa18a 2026-10-22T10:46:12+02:00
Review: approve (.ah-out/review/agent-hardening/T1.verdict.json)
Änderung: In `Run` nach der `--ca-fp`-Prüfung (`provision.go:89-94`) und vor `EnsureDataDir` (`:104-110`): `cacert != "" && insecure` → Fehler, der `--cacert` und `--insecure` nennt und sagt, dass `--cacert` den Server bereits prüft; der Kommentar `:89-91` nennt die Regel für alle drei Quellen. `pinIfBlindInsecure` (`:235-260`): `insecure && cacert == ""` ohne erfasste Kette (`len(serverCertPEM) == 0`) gibt einen Fehler zurück, statt `insecure` durchzureichen (`:242-244`); danach liefert die Funktion nie `insecure == true`. Die Signaturen von `pinIfBlindInsecure` und `runEnrollment` und die Variable `effectiveInsecure` bleiben. Tests in `provision_test.go`, Namen mit `TestProvisionTrust`: (a) `Run` mit `--cacert` (PEM-Datei in `t.TempDir()`) und `insecure` gegen einen httptest-TLS-Server mit Anfragezähler, `ADMINHELPER_*_DIR` und `applyWithoutBundle` wie in `TestRunRedeemsNothingWhenTheDataRootCannotBeSecured` (`:677-716`): Fehler nennt beide Flags, 0 Anfragen, weder `adminhelper.conf` noch `monitor.conf`; (b) `pinIfBlindInsecure("", true, nil)` → Fehler; (c) `pinIfBlindInsecure("", true, <PEM>)` → gepinnte Datei, `insecure == false` (Gegenstück zu b). `TestRunRejectsCAFPCombinedWithOtherTrust` (`:157-174`) bleibt grün. Zuerst rot: (a) und (b) auf HEAD.
Verify: bash scripts/dev/verify.sh agent --strict -- -run TestProvisionTrust
Doku: docs/admin/agent-deployment.html:188 + docs/en/admin/agent-deployment.html:187 (Absatz zu `--insecure`: bei `provision` nicht mit `--cacert` kombinierbar; ohne ein Zertifikat zum Pinnen bricht `provision` ab) · CHANGELOG.md (Changed, umlautfrei: `provision` lehnt `--cacert` zusammen mit `--insecure` ab, wie schon `--ca-fp` mit einem der beiden)
Beweis: Code-Lesung apps/agent/internal/provision/provision.go:89-94, :159-166, :241-244; apps/agent/internal/httpclient/httpclient.go:52-54
HEAD: b1432223

### T2 — monitor init: eine Vertrauensquelle, Pinnen oder Abbruch, nie `INSECURE=1`  [x]
Komponente: agent · Dateien: apps/agent/internal/monitor/monitor.go, apps/agent/internal/monitor/init_test.go, apps/agent/cmd/adminhelper-agent/main.go, docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, CHANGELOG.md
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @3c6773ff 2026-10-22T10:55:37+02:00
Review: approve (.ah-out/review/agent-hardening/T2.verdict.json)
Änderung: `Init` (`monitor.go:43-147`): (1) nach `RequireHTTPS` (`:51-54`), vor `EnsureDataDir` (`:56-61`): `cacert != "" && insecure` → Fehler wie in T1. (2) Blindes `--insecure` (`:86-98`): scheitert `fetchServerCertPEM`, liefert sie keine Kette oder scheitert das Speichern des Pins, gibt `Init` einen Fehler mit der Ursache zurück (Ausweg `--cacert`), bevor `monitor.conf` geschrieben ist; die Warnungen `:88` und `:92` entfallen. (3) `monitor.conf` bekommt nie `INSECURE`: der Zweig `:117-119` entfällt, der Test-Push (`:125-133`) nimmt nur `storedCACert`; der Kommentar `:81-85` passt dazu. (4) Naht `var enableTimer = enableMonitorService` in `monitor.go`, `Init` ruft sie statt `enableMonitorService` (`:141`); die Tests ersetzen sie durch einen Stub, der `t.Error` meldet, wenn er läuft. Verlegt agent-run-ctx die Timer-Aktivierung aus `Init`, entfällt die Naht mit dem Aufruf. (5) Hilfetext von `--insecure` bei `monitor init` (`apps/agent/cmd/adminhelper-agent/main.go:163`) englisch, sinngemäß wie bei `provision` (`:99`): nur dieser Aufruf, pinnt das vorgelegte Zertifikat. Tests in `init_test.go`, Namen mit `TestMonitorInitTrust`, `ADMINHELPER_MONITOR_DIR` auf `t.TempDir()`: (a) `--cacert` (Datei) und `insecure` gegen `https://127.0.0.1:1` → Fehler nennt beide Flags; weder `monitor.conf` noch `ca.crt`, Stub nicht gerufen; (b) blindes `insecure` gegen `https://127.0.0.1:1` (geschlossener Port wie `TestFetchServerCertPEMUnreachable`, `:35-40`) → Fehler; kein `monitor.conf`, Stub nicht gerufen. Zuerst rot: (a) und (b) auf HEAD, auf dem nur die Naht aus (4) steht.
Verify: bash scripts/dev/verify.sh agent --strict -- -run TestMonitorInitTrust
Doku: docs/admin/agent-deployment.html:188 + docs/en/admin/agent-deployment.html:187 (derselbe Absatz für `monitor init`: nicht mit `--cacert` kombinierbar; lässt sich das Zertifikat nicht holen oder speichern, bricht `monitor init` ab, statt die Prüfung abzuschalten) · CHANGELOG.md (Eintrag aus T1 um `monitor init` erweitert, umlautfrei)
Abhängt von: T1
Beweis: Code-Lesung apps/agent/internal/monitor/monitor.go:86-98, :114-119; apps/agent/internal/httpclient/httpclient.go:52-54
HEAD: b1432223

### T3 — `WriteSyncConfig` schreibt kein `INSECURE`  [x]
Komponente: agent · Dateien: apps/agent/internal/frpc/apply.go, apps/agent/internal/frpc/apply_test.go, docs/developer/agent.html, docs/en/developer/agent.html
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @c78e3930 2026-10-22T11:00:15+02:00
Review: approve (.ah-out/review/agent-hardening/T3.verdict.json)
Änderung: In `WriteSyncConfig` (`apply.go:45-100`) entfallen `confInsecure` und seine Zweige (`:74-81`, `:92-94`): `TLS.Insecure` ohne `CACert` schreibt keine Vertrauensangabe, der spätere Sync prüft dann gegen die System-CAs. Nach T1 übergibt `provision` ohnehin nie `Insecure`. `TestWriteSyncConfigStoresInsecureWithoutCA` (`apply_test.go:191-221`) wird durch `TestWriteSyncConfigNeverStoresInsecure` ersetzt: dieselbe Eingabe, erwartet `adminhelper.conf` mit genau `ADMINHELPER_URL`, `API_KEY`, `SERVER_ID` (ohne `INSECURE`, ohne `CACERT`) und kein `ca.crt`. Die Tests über `applyBundle` (`:229-237`) behalten `TLS: config.TLSOpts{Insecure: true}`; sie prüfen die frpc-Steuerung. Zuerst rot: der neue Test auf HEAD.
Verify: bash scripts/dev/verify.sh agent --strict -- -run TestWriteSyncConfig
Doku: docs/developer/agent.html:81 + docs/en/developer/agent.html:81 (`INSECURE` liest der Agent nur noch aus Konfigurationen früherer Versionen; `provision` und `monitor init` schreiben es nicht) · CHANGELOG: keiner (Eintrag aus T1/T2)
Abhängt von: T1
Test-Löschung: apps/agent/internal/frpc/apply_test.go::TestWriteSyncConfigStoresInsecureWithoutCA — ersetzt durch TestWriteSyncConfigNeverStoresInsecure im selben Commit; WriteSyncConfig schreibt INSECURE nicht mehr (gewollte Verhaltensänderung)
Beweis: Code-Lesung apps/agent/internal/frpc/apply.go:74-94
HEAD: b1432223

### T4 — Aktivierung: kein PKI-Bundle mehr entpacken  [x]
Komponente: agent · Dateien: apps/agent/internal/frpc/apply.go, apps/agent/internal/frpc/apply_test.go, apps/agent/internal/provision/provision.go, docs/developer/agent.html, docs/en/developer/agent.html, CHANGELOG.md
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @2e7d2821 2026-10-22T11:11:14+02:00
Review: approve (.ah-out/review/agent-hardening/T4.verdict.json)
Änderung: Es entfallen `ApplyParams.PkiBundleB64` (`apply.go:38`), der Entpack-Block in `Apply` (`:123-133`), `maxBundleBytes` und `extractPkiBundle` (`:161-253`) samt den Importen, die danach niemand braucht; in `provision.go` das Feld `PkiBundle` von `frpBundle` (`:44-47`) und `PkiBundleB64` im Aufruf von `frpc.Apply` (`:184`). Der Kommentar von `Apply` (`apply.go:102-107`) nennt kein Bundle mehr. Ein `pkiBundle` in der Antwort ignoriert `encoding/json` dann (der Server schickt `""`, `apps/server/app/modules/provisioning/helpers.py:107`). In `apply_test.go` gehen `makeBundle` (`:24-52`) und die fünf `TestExtractPkiBundle*` (`:54-140`) samt ungenutzten Importen. Nach dem Diff ist `grep -rn "PkiBundle\|pkiBundle\|extractPkiBundle\|maxBundleBytes" apps/agent` leer (Ergebnis in den Commit-Body). Kein neuer Test: die Funktion fällt weg, und ein Test über `provision.Run` mit FRP-Bundle käme an `systemctl` nicht vorbei (die frpc-Nähte liegen im Paket `frpc`).
Verify: bash scripts/dev/verify.sh agent --strict -- -run TestReprovision|TestRun
Doku: docs/developer/agent.html:46 + docs/en/developer/agent.html:46 (Paketzeile `frpc/`: „ZIP-Slip-sicher“ bzw. „zip-slip safe“ entfällt) · CHANGELOG.md (Removed, umlautfrei: der Agent entpackt kein PKI-Bundle aus der Aktivierungsantwort mehr; der Server schickt es seit 0.28.0 leer, und dieser Agent aktiviert nur ueber Port 8444, den es seit 0.39.0 gibt)
Abhängt von: T1, T3
Test-Löschung: apps/agent/internal/frpc/apply_test.go::TestExtractPkiBundleWritesFilesWithPermissions — extractPkiBundle entfällt samt Aufrufer; apps/agent/internal/frpc/apply_test.go::TestExtractPkiBundleRejectsZipSlip — extractPkiBundle entfällt samt Aufrufer; apps/agent/internal/frpc/apply_test.go::TestExtractPkiBundleRejectsGarbageBase64 — extractPkiBundle entfällt samt Aufrufer; apps/agent/internal/frpc/apply_test.go::TestExtractPkiBundleRejectsZipBomb — extractPkiBundle entfällt samt Aufrufer; apps/agent/internal/frpc/apply_test.go::TestExtractPkiBundleRejectsCumulativeOverLimit — extractPkiBundle entfällt samt Aufrufer
Beweis: Code-Lesung apps/server/app/modules/provisioning/helpers.py:107, apps/server/tests/test_provisioning.py:350, apps/agent/internal/provision/provision.go:68-70, apps/agent/internal/frpc/apply.go:123-133
HEAD: b1432223

### T5 — Kein `frp/pki` mehr: `config.FrpPkiDir` entfällt  [x]
Komponente: agent · Dateien: apps/agent/internal/config/paths.go, apps/agent/internal/frpc/apply.go, apps/agent/internal/frpc/apply_test.go, apps/agent/internal/config/securedir_windows.go, docs/developer/agent.html, docs/en/developer/agent.html, CHANGELOG.md
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @a04b56ac 2026-10-22T11:22:16+02:00
Review: approve (.ah-out/review/agent-hardening/T5.verdict.json)
Änderung: `FrpPkiDir` (`paths.go:21`) entfällt; `WriteSyncConfig` sichert nur noch `FrpDir` (`apply.go:52-61`), der Kommentar `:54-56` nennt keine Client-Keys mehr. Der Kommentar von `EnsureDataDir` (`securedir_windows.go:124-128`) zählt `frp, logs and identity` auf. Ein vorhandenes `pki/` (frühere Provisionierung, Pakete) bleibt unberührt. Neuer Test `TestWriteSyncConfigCreatesNoPkiDir` in `apply_test.go`: nach `WriteSyncConfig` gibt es `<FrpDir>/pki` nicht. Zuerst rot: der Test auf HEAD.
Verify: bash scripts/dev/verify.sh agent --strict -- -run TestWriteSyncConfig
Doku: docs/developer/agent.html:78, :79 + docs/en/developer/agent.html:78, :79 (`frp\pki` aus der Liste der gesicherten Verzeichnisse und aus „Lässt sich `frp` oder `frp\pki` nicht sichern …“) · CHANGELOG.md (Eintrag aus T4 ergänzt: der Agent legt kein `frp/pki` mehr an)
Abhängt von: T4
Beweis: Code-Lesung apps/agent/internal/config/paths.go:21, apps/agent/internal/frpc/apply.go:53-61
HEAD: b1432223

### T6 — diagnostics: jeder Bericht als neue Datei mit zufälligem Namensteil  [x]
Komponente: agent · Dateien: apps/agent/internal/diagnostics/diagnostics.go, apps/agent/internal/diagnostics/diagnostics_test.go, CHANGELOG.md
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @ba8edc69 2026-10-22T11:28:39+02:00
Review: approve (.ah-out/review/agent-hardening/T6.verdict.json)
Änderung: `Run` (`diagnostics.go:69-73`) legt den Bericht mit `os.CreateTemp("", "adminhelper-agent-diagnostics-"+ts+"-*.txt")` an (0600, nie eine vorhandene Datei), schreibt ihn, prüft `Close` und entfernt die Datei bei einem Fehler; der Pfad wird wie bisher ausgegeben (`:75`). Neuer Test `TestDiagnosticsReportIsANewFile` in `diagnostics_test.go`: `TMPDIR` (unter Windows `TMP`) auf `t.TempDir()`, `ADMINHELPER_MONITOR_DIR`, `ADMINHELPER_FRP_DIR` und `ADMINHELPER_LOG_DIR` auf leere Temp-Verzeichnisse; vor `Run` an jedem Namen `adminhelper-agent-diagnostics-<ts>.txt` für die UTC-Sekunden von jetzt − 1 s bis jetzt + 10 s ein Eintrag — unter Linux ein Symlink auf eine Datei außerhalb des Temp-Verzeichnisses, unter Windows eine Datei mit festem Inhalt. Danach: die Symlink-Ziele bzw. Dateien unverändert; genau eine neue Datei mit dem Präfix, die die Kopfzeile `AdminHelper agent diagnostics` enthält, unter Linux mit Modus 0600. Zuerst rot: der Test auf HEAD.
Verify: bash scripts/dev/verify.sh agent --strict -- -run TestDiagnosticsReport
Doku: keine Seite (`docs/admin/agent-deployment.html:205`, EN `:204` nennen nur `/tmp/`) · CHANGELOG.md (Changed, umlautfrei: `diagnostics` legt jeden Bericht als neue Datei mit zufaelligem Namensteil an (0600) und ueberschreibt keine vorhandene Datei)
Beweis: Code-Lesung apps/agent/internal/diagnostics/diagnostics.go:70-71
HEAD: b1432223

### T7 — frpc.toml des Servers nur in Generator-Form übernehmen  [x]
Komponente: agent · Dateien: apps/agent/internal/frpc/servertoml.go, apps/agent/internal/frpc/servertoml_test.go, apps/agent/internal/frpc/testdata/server_frpc.toml, apps/agent/internal/frpc/sync.go, apps/agent/internal/frpc/sync_flow_test.go, docs/developer/agent.html, docs/en/developer/agent.html, CHANGELOG.md, apps/agent/internal/frpc/testdata/.gitattributes
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @51bb4a9e 2026-10-22T11:50:05+02:00
Review: approve (.ah-out/review/agent-hardening/T7.verdict.json)
Änderung: Neue Datei `servertoml.go` (SPDX-Header wie `rewrite.go`) mit `checkServerConfig(serverToml []byte) error`; `applyConfig` ruft sie statt `checkServerHead` (`sync.go:189`), und `checkServerHead` samt `localHeadKeys` (`:300-318`) entfällt — die Schlüssel des lokalen Kopfs stehen nicht in der Allowlist. Regeln: (1) gültiges UTF-8, kein `{{`, kein Steuerzeichen außer dem Zeilenumbruch. (2) Jede Zeile ist nach Entfernen von Leerzeichen am Rand leer, `[transport.tls]`, `[[proxies]]` oder `<schlüssel> = <wert>`; jede andere Zeile, die mit `[` beginnt, und jede andere Form (Kommentar, Inline-Tabelle, mehrzeiliger oder Literal-String, Escape, Datum) wird abgelehnt. (3) Schlüssel: Segmente aus `A-Za-z0-9_-`, mit `.` verbunden, ohne Anführungszeichen. (4) Werte: Basic-String `"…"` ohne `"`, `\` und Steuerzeichen; Ganzzahl (TOML-dezimal, ohne `_`); Gleitzahl in den Formen, die Python `str(float)` schreibt (`1.5`, `1e+20`, `inf`, `-inf`, `nan`); `true`/`false`; Array aus Basic-Strings (`["a", "b"]`, auch `[]`). (5) Die Wurzel reicht bis zum ersten Tabellenkopf; `[transport.tls]` höchstens einmal und nur vor dem ersten `[[proxies]]`, die Schlüssel darunter zählen als `transport.tls.<schlüssel>`. In der Wurzel sind genau erlaubt: `serverAddr`, `serverPort`, `user`, `auth.method` (nur `"token"`), `auth.token`, `transport.tls.enable`, `transport.tls.trustedCaFile`, `transport.tls.certFile`, `transport.tls.keyFile` — als Punkt-Schlüssel in der Wurzel oder unter dem Kopf, nicht beides. (6) In jeder Tabelle (Wurzel, jedes `[[proxies]]`) kommt jeder volle Schlüsselpfad höchstens einmal vor, und keiner ist Präfix eines anderen. (7) In `[[proxies]]` ist auf dieser Stufe jeder Schlüssel nach (3) und (4) erlaubt (`extra_config` der Tunnel, Spec Trade-off 4; T8 schränkt ein). (8) Die Meldung nennt Zeilennummer und Schlüssel, nie den Wert — eine Zeile kann `auth.token` oder `secretKey` tragen (wie `parse_error` im Desktop, `apps/desktop/src-tauri/src/frpc.rs:468-484`). Fixture `testdata/server_frpc.toml` ohne SPDX-Kopf (sie ist Byte für Byte eine Ausgabe von `generate_frpc_toml`, T9 vergleicht): Wurzel und `[transport.tls]` wie `apps/server/app/modules/frp/config_generator.py:267-278` und `:160-171` mit `serverAddr` aus RFC 5737; ein STCP-Tunnel mit `secretKey` und `allowUsers` aus zwei Namen und `extra_config` aus `transport.bandwidthLimit = "1MB"`, `transport.useEncryption = true`, `healthCheck.intervalSeconds = 10`; ein HTTPS-Tunnel mit `customDomains` aus zwei Namen unter `.example`; die Tunnel in Namensreihenfolge, wie `active_tunnels` sie sortiert (`config_generator.py:134-142`); Token und Secret als Platzhalter. Tests in `servertoml_test.go`, Namen mit `TestServerConfig`: (a) angenommen: die Fixture, die Server-Texte der bestehenden Sync- und Apply-Tests (`tunnelToml`, `twoTunnelsToml`, `bundleToml` …) und ein Proxy mit den Gleitzahl-Formen aus (4); (b) abgelehnt, je ein Untertest: Zeile `[common]`; ein über mehrere Zeilen laufender Literal-String `user = '''` … `[common]` … `end = 1'''`; `"""`-String; Literal-String `'x'`; Inline-Tabelle; Kommentar; Escape `\"`; `{{` in einem Wert; `\r`; Schlüssel in Anführungszeichen; Wurzel-Schlüssel `includes`, `log.to`, `auth.tokenSource.type`, `store.path`, `webServer.port`, `loginFailExit`, `LOGINFAILEXIT`, `start`, `virtualNet.address`; `transport.tls.serverName`; `auth.method = "oidc"`; Köpfe `[[visitors]]`, `[proxies.plugin]`, `[log]`, ein zweites `[transport.tls]` und eines nach `[[proxies]]`; doppelter Schlüssel; Präfix-Konflikt (`transport = 1` und `transport.x = 2`); (c) die Meldung zu einer abgelehnten Zeile `auth.token = '<marker>'` enthält den Marker nicht; (d) über `Sync` mit den Helfern aus `sync_flow_test.go:36-101`: ein abgelehnter Text → Fehler, keine Datei geschrieben, kein Start oder Stopp, der Hash bleibt (wie `TestReloadRefusesALocalHeadFromTheServer`, `:957-991`, der unverändert grün bleibt); (e) über `Apply` (`applyBundle`, `apply_test.go:229-237`): ein abgelehnter Text → Fehler, keine `frpc.toml`. `TestReloadLocalHeadCheckLetsValuesPass` (`sync_flow_test.go:993-998`) ruft `checkServerConfig` statt `checkServerHead`; Eingabe und Erwartung bleiben. Zuerst rot: (d) mit `[common]`, dem mehrzeiligen Literal-String, `log.to` und `includes` auf HEAD, bevor (a)–(c) und der Fix stehen.
Verify: bash scripts/dev/verify.sh agent --strict -- -run TestServerConfig|TestReload
Doku: docs/developer/agent.html:97 + docs/en/developer/agent.html:97 (der letzte Satz: der Agent übernimmt einen Server-Text nur in der Form von `generate_frpc_toml` — einzeilige Werte, nur die Köpfe `[transport.tls]` und `[[proxies]]`, in der Wurzel nur die Schlüssel des Generators, kein `{{` —, sonst Fehler, er schreibt und startet nichts, und der nächste Lauf versucht es erneut) · CHANGELOG.md (Changed, umlautfrei: der Agent wendet eine frpc.toml des Servers nur in der Form an, die der Server erzeugt)
Beweis: Code-Lesung apps/agent/internal/frpc/sync.go:189, :300-318
HEAD: b1432223

### T8 — Proxy: kein Schlüssel der `plugin`-Familie  [x]
Komponente: agent · Dateien: apps/agent/internal/frpc/servertoml.go, apps/agent/internal/frpc/servertoml_test.go, docs/developer/agent.html, docs/en/developer/agent.html, docs/developer/api-reference.html, docs/en/developer/api-reference.html, CHANGELOG.md
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @8ae2e27b 2026-10-22T11:57:33+02:00
Review: approve (.ah-out/review/agent-hardening/T8.verdict.json)
Änderung: In einer `[[proxies]]`-Tabelle lehnt `checkServerConfig` jeden Schlüssel ab, dessen erstes Segment ohne Rücksicht auf ASCII-Groß-/Kleinschreibung `plugin` ist: frp ordnet Namen über `encoding/json` ohne Groß-/Kleinschreibung zu (Spec „Externe Integrationen“). Meldung mit Zeile und Schlüssel, ohne Wert. Tests mit `TestServerConfig`: abgelehnt `plugin.type = "static_file"`, `PLUGIN.type = "x"`, `Plugin.localPath = "/x"` und `plugin = "x"`; angenommen bleiben die Fixture und `transport.useCompression = true`. Zuerst rot: die abgelehnten Fälle auf dem Stand nach T7.
Verify: bash scripts/dev/verify.sh agent --strict -- -run TestServerConfig
Doku: docs/developer/agent.html:97 + docs/en/developer/agent.html:97 (Satz aus T7 ergänzt: in einem Proxy kein Schlüssel `plugin…`) · docs/developer/api-reference.html:141 + docs/en/developer/api-reference.html:141 (ein `extra_config`-Schlüssel, der mit `plugin` beginnt, wird gespeichert, der Agent wendet die Config des Hosts dann aber nicht an) · CHANGELOG.md (Eintrag aus T7 ergänzt, umlautfrei)
Abhängt von: T7
Beweis: Code-Lesung apps/server/app/modules/frp/schemas.py:51-76, apps/server/app/modules/frp/config_generator.py:297-309; Probe 2026-10-22 mit frpc 0.69.1 (`frpc verify -c`, dreimal identisch): `plugin.type = "no_such_plugin"` und `PLUGIN.type = "no_such_plugin"` in einem `[[proxies]]` → „unknown plugin type: no_such_plugin“
HEAD: b1432223

### T9 — Parität: die Fixture des Agents ist die Ausgabe von `generate_frpc_toml`  [x]
Komponente: server · Dateien: apps/server/tests/test_config_generator.py, apps/agent/internal/frpc/testdata/server_frpc.toml
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @d8b24a3e 2026-10-22T12:09:17+02:00
Review: approve (.ah-out/review/agent-hardening/T9.verdict.json)
Änderung: Neuer Test `test_agent_fixture_is_the_generator_output` in `test_config_generator.py`: baut mit `_make_config` (`:18-33`) und `_make_tunnel` (`:36-52`) die Konfiguration und die zwei Tunnel der Fixture aus T7 (gleiche Werte, `allow_users` mit zwei Namen) und vergleicht `generate_frpc_toml(...)` Zeichen für Zeichen mit der Datei `Path(__file__).resolve().parents[2] / "agent" / "internal" / "frpc" / "testdata" / "server_frpc.toml"` (Muster für eine Datei einer anderen Komponente: `tests/test_certificate_check.py:219`). Der Docstring sagt das Warum: ändert sich die Ausgabe des Generators, ziehen Fixture und Prüfung im Agent (`checkServerConfig`) nach. Weicht die Fixture aus T7 von der echten Ausgabe ab, gleicht T9 sie an; dann zusätzlich `bash scripts/dev/verify.sh agent --strict -- -run TestServerConfig` fahren und die Summary in den Commit-Body. Gegenprobe statt Rot-Lauf (der Test prüft eine Parität): ein geänderter Wert in einer Scratch-Kopie der Fixture macht den Test rot; Ergebnis in den Commit-Body.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_config_generator.py
Doku: keine (Test)
Abhängt von: T7
Orakel: contract — die Fixture der Agent-Prüfung ist eine echte Ausgabe des Generators; jede Abweichung macht den Test rot
HEAD: b1432223
