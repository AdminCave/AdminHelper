<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Install-, Update- und Agent-Skripte: Geheimnisse über Datei und stdin, nur der gepinnte Repo-Schlüssel, Prüfung der `.env` vollständig — Task-Ledger
Status: erledigt · Branch: feature/ops-install-hardening · Review: pro Task
Spec: docs/features/ops-install-hardening.md (Härtung, Kevin 2026-10-22)
Heavy: linux-full + scenario --agents 1 + windows — `linux-full`, weil die Agent-CLI (T1) und `install.sh`/`update.sh` im Diff sind (CLAUDE.md §5; `upgrade_path_test.sh` Schritt 4 startet die `update.sh` dieses Stands bis zur Übergabe, `agent_monitoring_test.sh` provisioniert mit `--token`). `scenario --agents 1` vor dem Merge, weil nur `scripts/tests/box_agentbox.sh:150-155` `agent-install.sh` mit echtem apt, echtem `Signed-By` auf den von T2 geschriebenen Keyring und echtem `provision` gegen den Agent aus diesem Checkout fährt (`box_serverbox.sh:328-396` baut Paket und Repo aus dem Checkout), also T1–T3 zusammen; `--rpm` fährt `agent-install.sh` nicht (`box_agentbox_rpm.sh:36` ruft `provision` direkt), den dnf-Zweig prüft `agent_install_test.sh`. `windows` über den CI-Job `agent-windows` (`go test` nativ; `main.go` hat kein Build-Tag, `verify.sh agent` baut zusätzlich mit `GOOS=windows`); der Pool hat keine Windows-Vorlage. Multibox bleibt ask-first
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Ziel: (1) Der Provisionierungs-Token geht über stdin an den Agent, nicht als Programmargument. (2) `agent-install.sh`
installiert aus der Keyring-Datei genau den gepinnten Schlüssel. (3) `install.sh` nimmt das Admin-Passwort aus einer
Datei. (4) `update.sh` stoppt vor dem ersten compose-Aufruf bei jedem `.env`-Fehler, an dem compose den Wert ausgäbe,
mit Schlüssel oder Zeilennummer statt Wert. Zeilenangaben: origin/main@b1432223; der builder greppt sie vor dem
Schreiben neu.

Für alle Tasks:
- Den PR merged Kevin (`install.sh`, `update.sh`, `agent-install.sh` im Diff, CLAUDE.md §2).
- Reihenfolge: T1 vor T3 (T3 nutzt den Flag aus T1 in der Doku und im echten Lauf), T2 vor T3 (dieselben Dateien);
  T4 und T5 sind unabhängig, T5 nach T4 (beide ändern `docs/*/installation.html`).
- `security` zusätzlich für T2, T3, T4 und T5 (`install.sh`/`update.sh` stehen auf `scripts/dev/review-risk.txt`;
  `agent-install.sh` trägt den Vertrauensanker der Paketquelle und reicht den Token weiter), für T1 empfohlen.
- Neue Meldungen, Hilfe- und Flag-Texte englisch; bestehende deutsche Texte bleiben.
- Keine Meldung und kein Log nennt einen Token, ein Passwort oder einen `.env`-Wert; Tests prüfen das mit einem
  Marker (`zz9…`) im Wert.
- Platzhalter: Hosts unter `example.com`/`.example`, Adressen aus RFC 5737; Schlüssel und Token in Tests sind
  Wegwerf-Werte des Tests.
- Abfrage der Agent-Hilfe einmal in eine Variable, dann `grep -q … <<<"$help"`; nie `cmd | grep -q` unter
  `pipefail` (ein früh endendes grep lässt `cmd` an SIGPIPE scheitern, und die Erkennung sagt falsch nein).

### T1 — Agent: `adminhelper-agent provision --token-stdin`  [x]
Komponente: agent · Dateien: apps/agent/cmd/adminhelper-agent/main.go, apps/agent/cmd/adminhelper-agent/provision_cmd_test.go, CHANGELOG.md
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @f622399d 2026-10-22T13:26:45+02:00
Review: approve (.ah-out/review/ops-install-hardening/T1.verdict.json)
Änderung: In `provisionCmd` (`main.go:84-105`) ein Bool-Flag `--token-stdin` („read the provision token from stdin“); statt `cmd.MarkFlagRequired("token")` (`:103`) `cmd.MarkFlagsOneRequired("token", "token-stdin")` und `cmd.MarkFlagsMutuallyExclusive("token", "token-stdin")` (cobra v1.10.2, `apps/agent/go.mod:7`). Mit `--token-stdin` liest `RunE` aus `cmd.InOrStdin()` höchstens 4 KiB bis zum ersten Zeilenumbruch und entfernt Leerraum und `\r` an den Enden; bleibt nichts, Fehler „no provision token on stdin“ ohne Inhalt. `provision.Run` (`apps/agent/internal/provision/provision.go:81`) wird über eine Paketvariable `runProvision` gerufen, damit der Test ihn ersetzt. Hilfe von `--token`: „provision token (or --token-stdin)“. Neue Testdatei `provision_cmd_test.go` mit SPDX-Header wie `box_cli_test.go:1-3`, Tests `TestProvisionCmd…` über `provisionCmd()` mit `SetArgs`, `SetIn`, `SetOut`/`SetErr` und ersetztem `runProvision` (per `t.Cleanup` zurück): (a) `--url https://srm.example.com --server-id sid-1 --token-stdin`, stdin `adminhelper_prov_test9\r\n` → `runProvision` bekommt `adminhelper_prov_test9`, URL und Server-ID unverändert; (b) `--token tok-1` ohne stdin → `tok-1` wie bisher; (c) beide Flags → Fehler, `runProvision` nicht gerufen; (d) keiner → Fehler, nicht gerufen; (e) `--token-stdin` mit leerem stdin und mit nur `\n` → Fehler, nicht gerufen, der Fehlertext nennt keinen Inhalt; (f) die Hilfe (`--help`) nennt `--token-stdin`. Zuerst rot: die neue Datei auf HEAD (unbekannter Flag, fehlende Variable). `box_cli_test.go` (Aufrufe mit `--token`, `:257`, `:294`) bleibt grün. Das Verify-Muster `Test[BP][or][xo]` trifft genau `TestBox…` und `TestPro…` (also `TestProvisionCmd…`), ohne `|` und Anführungszeichen: task-close reicht die Argumente ungequotet an `go test`, Anführungszeichen kämen wörtlich an.
Verify: bash scripts/dev/verify.sh agent --strict -- -run Test[BP][or][xo]
Doku: CHANGELOG.md (Added, umlautfrei: `adminhelper-agent provision --token-stdin` liest den Provisionierungs-Token von stdin); die Admin-Doku folgt in T3
Beweis: Code-Lesung apps/agent/cmd/adminhelper-agent/main.go:96, :103
HEAD: b1432223

### T2 — agent-install.sh: nur den Schlüssel mit dem gepinnten Fingerprint installieren  [x]
Komponente: scripts · Dateien: scripts/agent-install.sh, scripts/tests/agent_install_test.sh, docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, CHANGELOG.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @c4ed6b34 2026-10-22T13:43:26+02:00
Review: approve (.ah-out/review/ops-install-hardening/T2.verdict.json)
Änderung: `verify_keyring` (`agent-install.sh:172-184`) wird zu einer Funktion, die aus der heruntergeladenen Datei die zu installierende macht: Pin normalisieren und auf 40 Hex prüfen wie heute (`:179-181`), dann die Datei in ein frisches GNUPGHOME unter `$_TMPROOT` (`install -d -m 0700`) importieren, jeder gpg-Aufruf mit `--homedir`, `--batch` und `--no-autostart` (sonst startet gpg 2.4 einen gpg-agent für das Temp-Verzeichnis); Import scheitert → Abbruch „not a readable OpenPGP key“. Danach `gpg --export <Pin>` (für dnf mit `--armor`) in eine neue Datei und deren `--show-keys --with-colons` prüfen: genau ein `pub`-Record, und die `fpr`-Zeile direkt dahinter ist der Pin; sonst Abbruch wie heute (`:182`, Meldung nennt den erwarteten Fingerprint und die Primär-Fingerprints, die die Datei trägt). Installiert wird die exportierte Datei: apt `:193`, dnf `:240`. Damit fällt auch der Zugriff von `--show-keys` auf das GNUPGHOME des Aufrufers weg. Kopfkommentar `:14-19` und Kommentar `:172-174` sagen, dass nur der gepinnte Schlüssel installiert wird. Tests in `agent_install_test.sh` mit einem zweiten Wegwerf-Schlüssel in einem eigenen GNUPGHOME (der bestehende `FP`, `:38`, bleibt der des ersten): (a) apt, Keyring „gepinnt, dann fremd“ → Exit 0, der installierte Keyring hat genau einen `pub`, Fingerprint `FP`, der fremde fehlt; (b) apt, „fremd, dann gepinnt“ → ebenso; (c) dnf, beide armored in einer Datei → `RPM-GPG-KEY-adminhelper` ist armored mit genau einem `pub` = `FP`; (d) apt, Keyring nur mit dem fremden → Exit ≠ 0, weder Keyring noch `adminhelper.sources` geschrieben; (e) der gepinnte Schlüssel mit einem Unterschlüssel (`gpg --quick-add-key`), `--gpg-fp` = Fingerprint des Unterschlüssels → Exit ≠ 0, nichts geschrieben (`gpg --export` mit einem Unterschlüssel-Fingerprint liefert den ganzen Primärschlüssel, Spec Externe Integrationen). Zuerst rot: (a) (zwei `pub`), (b) (Abbruch), (c) (zwei `pub`). Die bestehenden Fälle (`:115-184`) bleiben grün.
Verify: bash scripts/dev/verify.sh scripts --strict -- agent_install_test doc_smoke_test
Doku: docs/admin/agent-deployment.html:52 + docs/en/admin/agent-deployment.html:52 (nach dem Fingerprint-Vergleich: installiert wird nur der Schlüssel mit diesem Fingerprint, auch wenn die Datei weitere trägt) · CHANGELOG.md (Changed, umlautfrei)
Beweis: Code-Lesung scripts/agent-install.sh:177, :193, :240
HEAD: b1432223

### T3 — agent-install.sh: Token über stdin an den Agent  [x]
Komponente: scripts · Dateien: scripts/agent-install.sh, scripts/tests/agent_install_test.sh, docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, CHANGELOG.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @6f586c44 2026-10-22T13:58:55+02:00
Review: approve (.ah-out/review/ops-install-hardening/T3.verdict.json)
Änderung: `agent-install.sh:318-334`: die Hilfe einmal holen (`help=$(adminhelper-agent provision --help 2>&1 || true)`); die Erkennung von `--ca-fp` (`:320`) prüft diese Variable statt einer Pipe. Nennt die Hilfe `--token-stdin`, bekommt `PROV_ARGS` statt `--token "$TOKEN"` den Flag `--token-stdin`, und der Aufruf ist `printf '%s\n' "$TOKEN" | adminhelper-agent provision "${PROV_ARGS[@]}"` (`printf` ist ein Builtin, kein Kindprozess mit dem Token in der Argumentliste). Sonst bleibt `--token "$TOKEN"`, mit einer Warnung, dass der installierte Agent `--token-stdin` nicht kennt und der Token als Programmargument übergeben wird (Rückfall wie bei `--ca-fp`, `:324-328`; Spec Trade-off 2). Tests in `agent_install_test.sh`: der Agent-Stub (`:70-91`) nennt in seiner Hilfe `--token-stdin`, außer mit `AH_STUB_NO_TOKEN_STDIN=1`, und schreibt bei `--token-stdin` sein stdin in `provision.stdin` (nur dann liest er stdin). (a) apt, `--token zz9tok-1` → `provision.args` enthält weder `zz9tok-1` noch `--token`, aber `--token-stdin`; `provision.stdin` ist `zz9tok-1`; Exit 0; (b) mit `AH_STUB_NO_TOKEN_STDIN=1` → `provision.args` enthält `--token` und `zz9tok-1`, die Ausgabe die Warnung; (c) die Fälle mit `--ca-fp` und `AH_STUB_NO_CAFP` (ab `:115`) laufen weiter grün über die gemeinsame Hilfe-Variable. Zuerst rot: (a).
Verify: bash scripts/dev/verify.sh scripts --strict -- agent_install_test doc_smoke_test
Doku: docs/admin/agent-deployment.html:52 + docs/en/admin/agent-deployment.html:52 (Satz zu `/dev/tty`: das Skript gibt den Token über stdin an den Agent weiter; ein Agent ohne `--token-stdin` bekommt ihn mit einer Warnung als Argument) · :179 / EN :178 (Tabelle `provision`: `--token`* oder `--token-stdin`*, eins von beiden) · CHANGELOG.md (Changed, umlautfrei)
Abhängt von: T1, T2
Beweis: Code-Lesung scripts/agent-install.sh:306-318, :334
HEAD: b1432223

### T4 — install.sh: `--admin-password-file`  [x]
Komponente: scripts · Dateien: scripts/install.sh, scripts/tests/install_test.sh, README.md, docs/admin/installation.html, docs/en/admin/installation.html, CHANGELOG.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @71f803a0 2026-10-22T14:12:54+02:00
Review: approve (.ah-out/review/ops-install-hardening/T4.verdict.json)
Änderung: Neuer Flag `--admin-password-file FILE` (Parser `install.sh:56-71`, Kopf `:17-18`). Gelesen direkt nach dem Parsen, vor dem Bootstrap und seinem `cd` (`:149-173`, `:172`), damit ein relativer Pfad gilt: nicht lesbar → Abbruch mit dem Pfad (nie dem Inhalt); die erste Zeile, ein `\r` am Ende entfernt; leer → Abbruch. `--admin-password` und `--admin-password-file` zusammen → Abbruch. `--admin-password` funktioniert weiter und schreibt auf stderr einen Hinweis, dass der Wert in der Prozessliste und der Shell-History steht und `--admin-password-file` das vermeidet. Die Meldung ohne Terminal (`:223`) nennt `--admin-password-file … --yes`. Die Länge prüft `:226` wie bisher; der Weg in den Container bleibt `--password-stdin` (`:297-300`). Tests in `install_test.sh`, neuer Abschnitt hinter Test 7 (`:218`), Checkout-Modus wie Test 5 (`:181-189`) mit Aufruf-Log des docker-Stubs (`:44-58`): (a) `--admin-password-file pw` (relativ, Inhalt `zz9pw-file1\n`) → Exit 0, `admin.stdin` ist `zz9pw-file1`, `zz9pw-file1` steht weder im Aufruf-Log noch in der Ausgabe; (b) Bootstrap-Modus wie Test 1 (`:118-121`, `--ref v0.34.0 --dir …`) mit relativem `--admin-password-file` aus dem Arbeitsverzeichnis des Aufrufs → Exit 0, Passwort angekommen; (c) Datei mit `zz9pw-crlf\r\n` → `admin.stdin` ist `zz9pw-crlf`; (d) fehlende Datei → Exit ≠ 0, Meldung nennt den Pfad, kein `compose pull|up` im Aufruf-Log; (e) leere Datei → Exit ≠ 0; (f) beide Flags → Exit ≠ 0; (g) `--admin-password zz9pw-arg` → Exit 0 und der Hinweis auf stderr. Zuerst rot: (a)–(f) (unbekannter Flag). Tests 1–7 bleiben grün.
Verify: bash scripts/dev/verify.sh scripts --strict -- install_test doc_smoke_test
Doku: README.md:176 (`--admin-password-file <datei> … --yes`) · docs/admin/installation.html:97 + docs/en/admin/installation.html:75 (Kommentar im Codeblock: nicht-interaktiv `--admin-password-file <datei> --yes`, die Datei nur für den Nutzer lesbar) · CHANGELOG.md (Added, umlautfrei; `--admin-password` bleibt mit Hinweis)
Beweis: Code-Lesung scripts/install.sh:18, :60, :223
HEAD: b1432223

### T5 — update.sh: Prüfung der `.env` auch für nicht geschlossene Anführungszeichen und ungültige Schlüssel  [x]
Komponente: scripts · Dateien: scripts/update.sh, scripts/tests/update_test.sh, docs/admin/installation.html, docs/en/admin/installation.html, CHANGELOG.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @77ab302f 2026-10-23T07:00:40+02:00
Review: approve (.ah-out/review/ops-install-hardening/T5.verdict.json)
Änderung: `check_env_templates` (`update.sh:124-167`) liest die `.env` weiter wie compose, mit Zeilennummer, und prüft zusätzlich: (1) ein Anführungszeichen, das bis zum Dateiende nicht schließt (heute `:152`, `:155` `return 0`) → Abbruch „der Wert von KEY hat ein nicht geschlossenes Anführungszeichen“; (2) jeden Schlüssel so, wie compose ihn liest (compose-go `locateKeyName`, Spec Externe Integrationen): Buchstaben und Ziffern, `_ . - [ ]`, Leerraum wird übersprungen, ein Leerzeichen im Schlüssel ist ein Fehler; Ende an `=`, `:` oder Zeilenende (eine Zeile ohne `=`/`:`, heute `:145` übergangen, ist ein Schlüssel ohne Wert und wird ebenso geprüft). Ein Fehler im Text hinter einem schließenden Anführungszeichen (`:158`, `:164`) → Abbruch „der Wert von KEY …“ mit dem Schlüssel des Werts davor; ein Fehler in einer Zeile für sich → Abbruch „der Eintrag in Zeile N …“; nie Wert oder Zeilentext. Nicht-ASCII-Zeichen beurteilt die Prüfung mit `[[:alpha:]]`/`[[:digit:]]` unter `LC_ALL=C.UTF-8` (glibc-Klassen ≈ `unicode.IsLetter`/`IsNumber`); ist die Locale nicht da, gilt ein Nicht-ASCII-Zeichen als erlaubt (lieber durchlassen als fälschlich ablehnen; Kommentar). Die bestehende Meldung (`:162-163`) und `env_template_ok` (`:78-99`) bleiben. Tests in `update_test.sh`: (a) Test 32 (`:845-882`) bekommt die Zeilen `SMTP_PASSWORD="zz9secret`, `SMTP_PASSWORD='zz9secret`, `SMTP_PASSWORD="zz9sec${ret`, `P='zz9ab'zz9cd'zz9ef${q'`, `P="zz9ab"zz9cd"zz9ef"`, `"SMTP_PASSWORD"=zz9secret`, `zz9stray!line`, `SMTP PASSWORD=zz9secret`, `P="zz9ab"zz9cd`, `ÄKEY=zz9v`, `a.b-c[0]=zz9v`, eine Zeile mit BOM vor `SMTP_PASSWORD=zz9v` und `zz9strayline`; die Prüfung auf die eigene Meldung (`:873-874`) nimmt neben „der Wert von“ auch „der Eintrag in Zeile“ an. (b) Für jede dieser Zeilen, die compose ablehnt: `zz9` steht nicht in der Ausgabe von `--check` (wie `assert_env_stop`, `:806-818`), und bei den Zeilen mit Schlüssel vor dem Wert nennt die Meldung `SMTP_PASSWORD` bzw. `P`. (c) Ein Update mit `SMTP_PASSWORD="zz9secret` am Ende der `.env` stoppt vor Backup, Snapshot und jedem compose-Aufruf außer `compose version` (wie Test 30). Zuerst rot: (a) für die abgelehnten Zeilen (heute rc 0), (b), (c). Tests 30–31 und die übrigen Zeilen von Test 32 bleiben grün.
Verify: bash scripts/dev/verify.sh scripts --strict -- update_test doc_smoke_test
Doku: docs/admin/installation.html:156 + docs/en/admin/installation.html:67 (ein Satz: auch ein nicht geschlossenes Anführungszeichen und Text direkt hinter dem schließenden, der kein gültiger Schlüssel ist, beenden jeden compose-Aufruf; `update.sh` prüft beides) · docs/admin/installation.html:213 + docs/en/admin/installation.html:166 (Schluss des Absatzes: bricht bei einem solchen Fehler ab, mit dem Schlüssel oder der Zeilennummer) · CHANGELOG.md (Changed, umlautfrei)
Abhängt von: T4
Beweis: Code-Lesung scripts/update.sh:145, :152-155, :158, :164
HEAD: b1432223
