<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Betriebsskripte, zweite Runde: Backup-Archiv robust am Zielnamen, Diagnose-Bundle liest die `.env` wie compose und maskiert genauer — Task-Ledger
Status: aktiv · Branch: feature/ops-scripts-2 · Review: pro Task
Spec: docs/features/ops-scripts-2.md (Roadmap R-0801, R-0804; T1, T3 und T5–T11 gehören zum Paket, Härtung, Kevin 2026-10-22)
Heavy: linux-full — `scripts/backup.sh` läuft real nur in `scripts/tests/backup_restore_test.sh` (`run.sh integration`, `scripts/tests/run.sh:893`: Backup gegen den laufenden Stack, Totalverlust, Restore), und `scripts/update.sh` ruft es vor jedem Update (`:363`, `:438`); der Sammellauf über `main` zeigt, dass das Archiv nach T1–T3 restorebar bleibt. Kein `scenario`: kein `multibox.sh`-Flag und kein `box_*.sh` ruft `backup.sh` oder `diagnostics.sh` auf; kein `windows`. `diagnostics.sh` fährt kein schwerer Lauf, `diagnostics_test.sh` prüft seine Funktionen und `main` mit Stubs
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Ziel: (1) Das Backup-Archiv liegt nach Exit 0 genau unter seinem Namen als Datei, seine Daten sind vor dem Umbenennen
auf der Platte, `--help` druckt nur den Kommentarkopf. (2) `env.sanitized` im Backup trägt `CA_ROOT_PASSPHRASE` in
keiner Zeilenform, die compose liest oder die auskommentiert ist. (3) Das Diagnose-Bundle findet die Secrets der
`.env` in den Formen, die compose liest, maskiert `SMTP_USER` immer, ist vom ersten Byte an 0600, und `--mask-hosts`
maskiert genauer; Kopf, `--help` und Doku sagen bei `SMTP_FROM` genau, was maskiert wird. Basis des Branches und aller
Zeilenangaben: `feature/ops-scripts-hardening@73bf0d31` (PR #266, bei der Planung nicht gemergt); der builder greppt
sie vor dem Schreiben neu.

Für alle Tasks:
- Reihenfolge T1 → T11, nacheinander (ein Bauer je Ledger): T1–T3 ändern `scripts/backup.sh` und
  `scripts/tests/restore_guard_test.sh`, T4–T11 `scripts/diagnostics.sh` und `scripts/tests/diagnostics_test.sh`;
  beide Ketten teilen `CHANGELOG.md`, T4, T5 und T8 dazu die Troubleshooting-Seiten.
- T1, T3 und T5–T8 bekommen zusätzlich `security` (Dateien mit Secrets: Backup-Archiv, Diagnose-Bundle).
- Kein Task ändert `scripts/install.sh`, `scripts/update.sh` oder `scripts/agent-install.sh`.
- Neue Meldungen und Hilfetexte englisch; die bestehenden deutschen Texte bleiben.
- Platzhalter: Adressen aus RFC 5737 (`192.0.2.x`, `198.51.100.x`, `203.0.113.x`), IPv6 aus `2001:db8::/32`, Namen
  unter `.example`/`example.com`/`example.org`. Zeichenklassen in Mustern ausgeschrieben (unter `de_DE` matchen
  Bereiche wie `A-Z` auch Umlaute); Byte-Muster unter `LC_ALL=C`.
- Tests, die eine UTF-8-Locale brauchen, laufen unter `LC_ALL=C.UTF-8`; fehlt sie, endet der Test mit 75 (SKIP), nicht
  grün (`restore_guard_test.sh` über `LOCALE_SKIP`, `diagnostics_test.sh` wie Fall (c)).
- `verify.sh scripts` fährt `shellcheck --severity=warning` über `scripts/*.sh` und `scripts/tests/*.sh` mit
  (`scripts/tests/run.sh:636-639`). Doku-Tasks fahren dazu `python3 scripts/dev/doc-smoke.py --paths --env --strict`
  (die Prüfung der CI, `.github/workflows/ci.yml:874`) und nennen das Ergebnis im Commit-Body.
- CHANGELOG umlautfrei und als gewünschtes Verhalten formuliert. Solange die Einträge von ops-scripts-hardening unter
  `[Unreleased]` stehen (`CHANGELOG.md:12-20` Added, `:67` Changed, `:125` und `:135` Fixed), passen die Tasks diese
  an, statt doppelte Einträge zu schreiben; sonst ein eigener Eintrag.

### T1 — backup.sh: das Archiv liegt nach Exit 0 als Datei unter seinem Namen  [x]
Komponente: scripts · Dateien: scripts/backup.sh, scripts/tests/restore_guard_test.sh, CHANGELOG.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @99deecd4 2026-10-23T19:38:53+02:00
Review: approve (.ah-out/review/ops-scripts-2/T1.verdict.json)
Änderung: `backup.sh:138` `mv -f "$PARTIAL" "$ARCHIVE"` wird `mv -fT -- "$PARTIAL" "$ARCHIVE"` (GNU `--no-target-directory`, wie `scripts/update.sh:495`): ein Verzeichnis unter dem Archivnamen nimmt das Archiv nicht mehr auf, das Backup bricht mit einer englischen Meldung auf stderr und Exit 1 ab, der EXIT-Trap (`:52`) entfernt die Zwischendatei; ein Symlink unter dem Namen wird durch das Archiv ersetzt, sein Ziel bleibt unberührt. Der Kommentar `:131-135` nennt das Warum in einem Satz. Tests in `restore_guard_test.sh`, neuer Fall 16 (der Kopf `:1-29` nennt ihn) mit den Stubs von Fall 10/11 (`:178-215`) und einem `date`-Stub in `$WORK/bk/bin`, der für `+%Y-%m-%d_%H-%M-%S` `2026-10-22_10-00-00` ausgibt und sonst das echte `date` aufruft (Pfad vor dem PATH-Tausch gemerkt, wie `AH_TEST_REAL_TAR`): (a) im Zielordner liegt vorab ein leeres Verzeichnis `adminhelper-backup-2026-10-22_10-00-00.tar.gz` → Exit ≠ 0, das Verzeichnis ist weiter leer, im Zielordner liegt keine Datei `.adminhelper-backup-*`; (b) unter dem Namen liegt ein Symlink auf ein leeres Verzeichnis außerhalb des Zielordners → Exit 0, der Name ist eine reguläre Datei (kein Symlink) mit Modus 600, `tar tzf` listet `./MANIFEST.txt`, das Verzeichnis außerhalb ist leer. Zuerst rot: (a) (Exit 0, das Archiv liegt im Verzeichnis) und (b) (das Archiv liegt im Ziel des Symlinks). Die Fälle 1–15 bleiben grün.
Verify: bash scripts/dev/verify.sh scripts --strict -- restore_guard_test
Doku: CHANGELOG.md (den Changed-Eintrag „Backup: Archiv von Anfang an privat …“ `:67` ergänzen, umlautfrei: liegt unter dem Archivnamen schon ein Verzeichnis, bricht das Backup ab, statt das Archiv hineinzulegen; ein Symlink unter dem Namen wird durch das Archiv ersetzt)
Beweis: Code-Lesung scripts/backup.sh:138
HEAD: 73bf0d31

### T2 — backup.sh: Archiv vor dem Umbenennen auf der Platte, `--help` nur der Kommentarkopf (R-0801)  [x]
Komponente: scripts · Dateien: scripts/backup.sh, scripts/tests/restore_guard_test.sh, CHANGELOG.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @0a7658db 2026-10-23T19:49:58+02:00
Review: approve (.ah-out/review/ops-scripts-2/T2.verdict.json)
Änderung: (1) Zwischen `tar` (`:137`) und `mv` (`:138`) `sync -- "$PARTIAL"` (nur diese Datei, kein globales `sync`), nach dem `mv` `sync -- "$OUT_DIR"` (der neue Verzeichniseintrag). Scheitert ein `sync`, endet das Skript mit Exit ≠ 0 und einer englischen Meldung; scheitert der erste, bleibt kein Archiv und keine Zwischendatei zurück. Der Kommentar `:131-135` nennt das Warum. (2) `--help` (`:37`, heute `sed -n '2,30p'`: hinter der Usage-Zeile `:23` stehen auch `set -euo pipefail`, `umask 077` und `OUT_DIR="./backups"`) druckt den Kommentarkopf ab Zeile 2 bis vor die erste Zeile, die nicht mit `#` beginnt, ohne feste Zeilennummer (etwa `awk 'NR > 1 { if (!/^#/) exit; print }' "$0"`). Tests in `restore_guard_test.sh`: Fall 17 mit einem `sync`-Wrapper in `$WORK/bk/bin`, der je Aufruf seine Argumente und `stat -c '%F %s'` des letzten Arguments ins Protokoll schreibt und dann das echte `sync` aufruft, mit `AH_TEST_SYNC_FAIL=1` stattdessen Exit 1: (a) Erfolg → genau zwei Aufrufe, zuerst eine nicht leere reguläre Datei `.adminhelper-backup-*` im Zielordner, danach der Zielordner, der dann genau das Archiv enthält; (b) `AH_TEST_SYNC_FAIL=1` → Exit ≠ 0, der Zielordner ist leer. Fall 18: `backup.sh --help` → Exit 0, die letzte Zeile ist `#   ./scripts/backup.sh [--with-victoria] [--output DIR]`, jede Zeile beginnt mit `#`. Zuerst rot: 17 (a) (kein Aufruf), 17 (b) (Exit 0, Archiv da) und 18 (letzte Zeile `OUT_DIR="./backups"`). Die Fälle 1–16 bleiben grün.
Verify: bash scripts/dev/verify.sh scripts --strict -- restore_guard_test
Doku: CHANGELOG.md (den Changed-Eintrag `:67` ergänzen, umlautfrei: die Daten des Archivs sind vor dem Umbenennen auf der Platte; `--help` zeigt nur die Hilfe)
Abhängt von: T1
Beweis: feature/ops-scripts-hardening@73bf0d31 · `grep -n sync scripts/backup.sh` → keine Zeile; `sed -n '2,30p' scripts/backup.sh | tail -6` → `set -euo pipefail`, zwei Kommentarzeilen, `umask 077`, Leerzeile, `OUT_DIR="./backups"`
Orakel: contract — nach Exit 0 trägt der Archivname ein vollständig geschriebenes Archiv; `--help` ist der Kommentarkopf bis zur Usage-Zeile
Dedup-Key: ref:scripts:backup-fsync-help
HEAD: 73bf0d31
Semantik: `docs/admin/betrieb.html:92` — „Das Archiv … trägt seinen Namen erst, wenn es vollständig geschrieben ist“ (EN `docs/en/admin/operations.html:59` „gets its name only once it is completely written“)

### T3 — backup.sh: `env.sanitized` ohne `CA_ROOT_PASSPHRASE` auch auskommentiert, hinter BOM oder Unicode-Leerraum und über mehrere Zeilen  [ ]
Komponente: scripts · Dateien: scripts/backup.sh, scripts/tests/restore_guard_test.sh, CHANGELOG.md
Änderung: Der Filter `backup.sh:111` (`grep -a -v -E …`) wird ein `awk`-Programm unter `LC_ALL=C`: byte-treu wie bisher, jede übrige Zeile unverändert, die letzte Zeile endet mit einem Zeilenumbruch wie bei grep. Entfernt wird eine Zeile, wenn auf ihren Anfang — beliebig viel aus ASCII-Leerraum, BOM (`EF BB BF`) und den UTF-8-Formen von Unicode-Leerraum (`C2 85`, `C2 A0`, `E1 9A 80`, `E2 80 80` bis `E2 80 8A`, `E2 80 A8`, `E2 80 A9`, `E2 80 AF`, `E2 81 9F`, `E3 80 80`), dann optional `#`-Zeichen mit Leerraum, dann optional `export` und Leerraum — der Schlüssel `CA_ROOT_PASSPHRASE` folgt, danach Leerraum (auch `C2 85`, `C2 A0`) und `=` oder `:`. Beginnt der Wert einer nicht auskommentierten solchen Zeile (nach Leerraum) mit `"` oder `'` und schließt das passende Anführungszeichen auf der Zeile nicht (in `"…"` zählt ein `"` hinter einer ungeraden Zahl `\` nicht, in `'…'` ein `'` hinter `\` nicht), werden die Folgezeilen bis einschließlich der schließenden entfernt, ohne schließendes bis zum Dateiende. `CA_ROOT_PASSPHRASE_OLD` und andere Schlüssel mit diesem Präfix bleiben, auch auskommentiert. Exit-Behandlung und Meldungen (`:111-114`) bleiben; der Kommentar `:104-110` nennt die Formen. Tests in `restore_guard_test.sh`, Fall 19 unter `LC_ALL=C.UTF-8` (ohne die Locale über `LOCALE_SKIP` wie Fall 12): eine `.env` per `printf` mit Byte-Escapes aus `\xef\xbb\xbfCA_ROOT_PASSPHRASE=bom1`, `A=1`, `#CA_ROOT_PASSPHRASE=old1`, `  # export CA_ROOT_PASSPHRASE = old2`, `\xc2\xa0CA_ROOT_PASSPHRASE=nbsp1`, `\xe2\x80\x83CA_ROOT_PASSPHRASE=em1`, `CA_ROOT_PASSPHRASE\xc2\xa0=sep1`, `CA_ROOT_PASSPHRASE="ml1`, `ml2`, `ml3"`, `B=2`, `CA_ROOT_PASSPHRASE='sq1`, `sq2'`, `CA_ROOT_PASSPHRASE="esc\"q1`, `esc2"`, `CA_ROOT_PASSPHRASE_OLD=keep`, `#CA_ROOT_PASSPHRASE_OLD=keep2`, `Y=caf\xc3\xa9` und `Z=last` ohne abschließenden Zeilenumbruch → `env.sanitized` aus dem Archiv ist byte-gleich (`cmp`) mit `A=1\nB=2\nCA_ROOT_PASSPHRASE_OLD=keep\n#CA_ROOT_PASSPHRASE_OLD=keep2\nY=caf\xc3\xa9\nZ=last\n`; eine zweite `.env` `A=1\nCA_ROOT_PASSPHRASE="open1\nrest1\nrest2\n` → `A=1\n`. Zuerst rot: beide (Passphrase- bzw. Folgezeilen stehen im Archiv). Die Fälle 1–18 bleiben grün, insbesondere 12–15.
Verify: bash scripts/dev/verify.sh scripts --strict -- restore_guard_test
Doku: CHANGELOG.md (den Fixed-Eintrag „Backup: `env.sanitized` verliert keine Zeilen mehr …“ `:125` ergänzen, umlautfrei: entfernt werden auch auskommentierte Zeilen, Zeilen mit BOM oder Unicode-Leerraum vor dem Schluessel und die Folgezeilen eines mehrzeiligen Werts)
Abhängt von: T2
Beweis: Code-Lesung scripts/backup.sh:111
HEAD: 73bf0d31

### T4 — Wortlaut zu `SMTP_FROM`: maskiert wird die Adresse, nicht der Anzeigename (R-0804)  [x]
Komponente: scripts · Dateien: scripts/diagnostics.sh, scripts/tests/diagnostics_test.sh, docs/admin/troubleshooting.html, docs/en/admin/troubleshooting.html, README.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @dafefceb 2026-10-23T19:36:43+02:00
Review: approve (.ah-out/review/ops-scripts-2/T4.verdict.json)
Änderung: Der Kopf `diagnostics.sh:17-22`, `docs/admin/troubleshooting.html:147`, `docs/en/admin/troubleshooting.html:135` und `README.md:309` sagen bei `--mask-hosts`, dass von `SMTP_FROM` mit Anzeigenamen (`Name <adresse>`) nur die Adresse maskiert wird und der Name stehen bleibt (DE etwa „bei <code>SMTP_FROM</code> mit Anzeigenamen nur die Adresse in spitzen Klammern, nicht der Name“; der Satz bleibt nach T9 richtig). `--help` (`:40`, `sed -n '2,27p'`, endet heute genau auf der Usage-Zeile `:27` und verrutscht mit jeder neuen Kopfzeile) druckt den Kommentarkopf ab Zeile 2 bis vor die erste Zeile, die nicht mit `#` beginnt, ohne feste Zeilennummer (wie backup.sh nach T2). Das Maskieren selbst ändert sich nicht. Test in `diagnostics_test.sh`, Fall (h) (`:452-460`): `--help` nennt die Einschränkung (`angle brackets`), seine letzte Zeile ist `#   ./scripts/diagnostics.sh [--tail N] [--output DIR] [--mask-hosts]`. Zuerst rot: die Prüfung auf `angle brackets`.
Verify: bash scripts/dev/verify.sh scripts --strict -- diagnostics_test doc_smoke_test
Doku: die Seiten oben (DE + EN, README); CHANGELOG bleibt (`CHANGELOG.md:15` sagt es schon richtig)
Beweis: feature/ops-scripts-hardening@73bf0d31 · Code-Lesung scripts/diagnostics.sh:114-117 (von einem Wert mit `<…>` wird nur der Klammerinhalt Regel) gegen den Kopf :17-20 („the names and addresses set in … SMTP_FROM … become <host>“), docs/admin/troubleshooting.html:147, docs/en/admin/troubleshooting.html:135, README.md:309
Orakel: contract — Kopf, `--help`, Doku und README beschreiben, was `host_rules` maskiert
Dedup-Key: bug:docs:smtp-from-mask-wording
HEAD: 73bf0d31
Semantik: `scripts/tests/diagnostics_test.sh:331` — „Of a display name ("Name <address>", as in SMTP_FROM) only the address is a host value“; `CHANGELOG.md:15` — „bei einem Anzeigenamen nur die Adresse in spitzen Klammern“

### T5 — diagnostics.sh: `SMTP_USER` wird immer maskiert wie die übrigen Zugangsdaten  [ ]
Komponente: scripts · Dateien: scripts/diagnostics.sh, scripts/tests/diagnostics_test.sh, docs/admin/troubleshooting.html, docs/en/admin/troubleshooting.html, README.md, CHANGELOG.md
Änderung: `SMTP_USER` wandert aus `HOST_KEYS` (`:54`) nach `SECRET_KEYS` (`:49`): auch ohne Schalter steht in `env.sanitized` `SMTP_USER=<redacted>`, und sein Wert wird in `report.txt` und den Logs `<redacted>`; kein Schalter stellt das ab. Die Wertregel für `SMTP_USER` (in `build_redaction_sedfile`, `:59-87`) bekommt `\b` an Rändern aus Wortzeichen (wie `host_rules`, `:127`), damit ein kurzer Benutzer wie `admin` nicht in `adminhelper` greift; die Regeln der übrigen Secrets bleiben ohne Wortgrenze. Der Kopf `:12-22` nennt `SMTP_USER` bei den Zugangsdaten statt bei den Host-Schlüsseln. Tests in `diagnostics_test.sh`, neuer Fall (j) (der Kopf `:1-36` nennt ihn): `.env` mit `SMTP_USER=relay9user@mail.example.com` → ohne `--mask-hosts` hat `sanitize_env` `SMTP_USER=<redacted>`, die Logzeile `auth as relay9user@mail.example.com ok` wird `auth as <redacted> ok`; `.env` mit `SMTP_USER=admin` → `adminhelper-server-1 started` bleibt, `login admin failed` wird `login <redacted> failed`. Zuerst rot: der Wert steht ohne Schalter in `env.sanitized` und in der Logzeile. Die Fälle (a)–(i) bleiben grün (keiner nutzt `SMTP_USER`).
Verify: bash scripts/dev/verify.sh scripts --strict -- diagnostics_test doc_smoke_test
Doku: docs/admin/troubleshooting.html:147 + :150 (`SMTP_USER` aus der Liste der Host-Schlüssel; Callout „Die Secrets der .env (SECRET_KEY, Passwörter, SMTP-Benutzer)“) · docs/en/admin/troubleshooting.html:135 + :138 ebenso · README.md:309 ebenso („SMTP host and sender“, „SECRET_KEY, passwords, SMTP user“) · CHANGELOG.md (im Added-Eintrag `:12-20` `SMTP_USER` aus der Liste nehmen; dazu Changed, umlautfrei: das Diagnose-Bundle maskiert `SMTP_USER` immer wie die Passwoerter)
Abhängt von: T4
Beweis: Code-Lesung scripts/diagnostics.sh:49, :54
HEAD: 73bf0d31

### T6 — diagnostics.sh: Schlüssel hinter BOM und Unicode-Leerraum, auskommentierte Zeilen in `env.sanitized`  [ ]
Komponente: scripts · Dateien: scripts/diagnostics.sh, scripts/tests/diagnostics_test.sh, CHANGELOG.md
Änderung: Ein gemeinsames Präfix-Muster für `env_values` (`:137-142`) und `sanitize_env` (`:183-196`) erkennt vor dem Schlüssel außer ASCII-Leerraum auch BOM und die UTF-8-Formen von Unicode-Leerraum (Liste wie T3, `LC_ALL=C`, Bytes ausgeschrieben) und zwischen Schlüssel und Trenner auch `C2 85` und `C2 A0` (so liest compose, Spec „Externe Integrationen“); in `env.sanitized` behält die Zeile ihre Form bis zum Wert. Auskommentierte Zeilen eines Secret-Schlüssels (ein oder mehr `#`, Leerraum davor und danach, optional `export`) werden in `env.sanitized` `#KEY=<redacted>` (Form bis zum Wert bleibt), die eines Host-Schlüssels mit `--mask-hosts` `<masked>`. Ihre Werte werden keine Log-Regeln: eine auskommentierte Zeile ist keine Konfiguration, und `.env.example` trägt dort Beispielwerte (`:35`, `:133`). Tests in `diagnostics_test.sh`, neuer Fall (k) unter `LC_ALL=C.UTF-8` (ohne die Locale wie Fall (c)): `.env` aus `\xef\xbb\xbfSECRET_KEY=bom9secret`, `\xc2\xa0POSTGRES_PASSWORD=nbsp9secret`, `\xe2\x80\x83MONITOR_API_KEY=em9secret`, `ADMIN_PASSWORD\xc2\xa0=sep9secret`, `#ADMIN_PASSWORD=old9secret`, `  # SMTP_PASSWORD = old9smtp`, `#DOMAIN=old9.example.com` und `A=keep9` → Logzeilen mit `bom9secret`, `nbsp9secret`, `em9secret` und `sep9secret` sind maskiert; `sanitize_env` enthält keinen der sechs Secret-Werte, hat `#ADMIN_PASSWORD=<redacted>` und `  # SMTP_PASSWORD = <redacted>`, `A=keep9` bleibt; `sanitize_env … 1` hat `#DOMAIN=<masked>`. Zuerst rot: die vier Werte in den Logs, die sechs in `env.sanitized`, `#DOMAIN`.
Verify: bash scripts/dev/verify.sh scripts --strict -- diagnostics_test
Doku: CHANGELOG.md (den Fixed-Eintrag „Diagnose-Bundle: Maskierung kennt …“ `:135` ergänzen, umlautfrei: Schluessel hinter BOM oder Unicode-Leerraum; auskommentierte Zeilen dieser Schluessel in `env.sanitized` maskiert)
Abhängt von: T5
Beweis: Code-Lesung scripts/diagnostics.sh:137-142, :183-196
HEAD: 73bf0d31

### T7 — diagnostics.sh: Werte mit Escapes und über mehrere Zeilen so, wie compose sie liest  [ ]
Komponente: scripts · Dateien: scripts/diagnostics.sh, scripts/tests/diagnostics_test.sh, CHANGELOG.md
Änderung: `env_value_forms` (`:152-165`) liefert den Wert, wie compose ihn liest: in doppelten Anführungszeichen endet er am ersten nicht durch `\` maskierten `"` (heute am ersten `"`, `:159`), `\a \b \f \n \r \t \v \$ \" \\` und Oktal `\0nnn` werden dekodiert, `$$` → `$` wie bisher; in einfachen Anführungszeichen wird `\'` zu `'`. Ein Wert in Anführungszeichen, der auf seiner Zeile nicht schließt, läuft über die Folgezeilen bis zum schließenden Anführungszeichen, ohne eines bis zum Dateiende; `env_values` (`:137-142`) liest dafür die Datei statt einzelner grep-Zeilen (byte-treu, `LC_ALL=C`). Jede nicht leere Zeile eines mehrzeiligen (auch eines durch `\n` mehrzeilig dekodierten) Werts wird eine eigene Regel; weicht die Dateiform ab, werden beide gesucht wie bisher. `sanitize_env` macht aus der ersten Zeile `KEY=<redacted>` und lässt die Folgezeilen des Werts weg. `host_rules` liest die Host-Werte auf demselben Weg. Tests in `diagnostics_test.sh`, neuer Fall (l): `.env` aus `SECRET_KEY="ab\"cd9esc"`, `POSTGRES_PASSWORD="pq\\9bs"`, `MONITOR_API_KEY='sq\'9sq'`, `ADMIN_PASSWORD='ml9first`, `ml9second'`, `SMTP_PASSWORD="dq9first`, `dq9second"` und `Z=after9` → Logzeilen mit `ab"cd9esc`, `pq\9bs`, `sq'9sq`, `ml9first`, `ml9second`, `dq9first` und `dq9second` sind maskiert; `sanitize_env` enthält keinen dieser Werte und keine Folgezeile, hat `ADMIN_PASSWORD=<redacted>` und `SMTP_PASSWORD=<redacted>`, `Z=after9` bleibt; eine zweite `.env` aus `SECRET_KEY="open9first` und `open9second` ohne schließendes `"` → beide Teile in den Logs maskiert, `sanitize_env` ist genau `SECRET_KEY=<redacted>`. Zuerst rot: jede dieser Prüfungen (Probe am Stand 73bf0d31, Spec Problem 6). Fall (b) und der `sanitize_env`-Fall (`:137-218`) bleiben grün.
Verify: bash scripts/dev/verify.sh scripts --strict -- diagnostics_test
Doku: CHANGELOG.md (den Fixed-Eintrag `:135` ergänzen, umlautfrei: Werte mit Escape-Sequenzen und Werte ueber mehrere Zeilen werden gefunden; `env.sanitized` laesst die Folgezeilen weg)
Abhängt von: T6
Beweis: Code-Lesung scripts/diagnostics.sh:152-165
HEAD: 73bf0d31

### T8 — diagnostics.sh: Bundle vom ersten Byte an 0600 und erst vollständig unter seinem Namen, Host-Regeln nicht als Argument  [ ]
Komponente: scripts · Dateien: scripts/diagnostics.sh, scripts/tests/diagnostics_test.sh, docs/admin/troubleshooting.html, docs/en/admin/troubleshooting.html, CHANGELOG.md
Änderung: (1) `main` (`:198`) setzt zu Beginn `umask 077` (in `main`, nicht beim `source` durch den Test): Stage, Regel-Datei und Bundle gehören nur dem ausführenden Nutzer. Das Bundle (`:261-262`) entsteht als `mktemp "${OUT_DIR%/}/.adminhelper-diagnostics-${ts}.XXXXXX"`, `tar -czf` schreibt dorthin, danach `mv -fT --` auf den Namen (wie backup.sh nach T1); der EXIT-Trap (`:209`) entfernt die Zwischendatei, solange sie existiert (Variable vorher leer, `rm -f --`, kein Glob). Eine vorhandene Datei unter dem Namen wird ersetzt, statt mit ihrem Modus überschrieben zu werden. (2) `sanitize_env` (`:191`, `:195`) gibt die Host-Regeln nicht mehr mit `-e "$rules"` an `sed`, sondern per `sed -f` (Prozess-Substitution oder eine Datei im Stage-Ordner, die wie `.redact.sed` vor dem `tar` entfernt wird, `:259`): kein Wert der `.env` steht in der Argumentliste eines Prozesses. Tests in `diagnostics_test.sh`, neuer Fall (m) in einem eigenen Arbeitsordner mit den Stubs von Fall (e) (`:368-400`), unter `umask 022`: ein `date`-Stub gibt für `-u +%Y%m%dT%H%M%SZ` `20261022T100000Z` aus (sonst das echte `date`), vorab liegt `adminhelper-diagnostics-20261022T100000Z.tar.gz` mit Modus 644 und dem Inhalt `old` im Zielordner; ein `sed`-Wrapper schreibt seine Argumente ins Protokoll und ruft das echte `sed` (Pfad vor dem PATH-Tausch gemerkt); `.env` zusätzlich mit `EXTRA_SANS=argv9.example.com` und `ADMIN_PASSWORD=argv9secret`; Lauf mit `--mask-hosts` → Exit 0, das Bundle hat Modus 600 und ist ein lesbares Archiv mit `report.txt`, im Zielordner liegt keine `.adminhelper-diagnostics-*`; das Protokoll enthält weder `argv9.example.com` noch `argv9secret`. Zuerst rot: Modus 644 und `argv9.example.com` im Protokoll.
Verify: bash scripts/dev/verify.sh scripts --strict -- diagnostics_test doc_smoke_test
Doku: docs/admin/troubleshooting.html:147 + docs/en/admin/troubleshooting.html:135 (ein Satz: das Bundle ist nur für den ausführenden Nutzer lesbar, `0600`; mit `sudo` gestartet gehört es root) · CHANGELOG.md (Changed, umlautfrei: das Diagnose-Bundle ist von Anfang an nur fuer den ausfuehrenden Nutzer lesbar und traegt seinen Namen erst, wenn es vollstaendig geschrieben ist)
Abhängt von: T7
Beweis: Code-Lesung scripts/diagnostics.sh:191, :195, :262
HEAD: 73bf0d31

### T9 — diagnostics.sh `--mask-hosts`: jede Adresse eines Host-Werts und der kurze Rechnername  [ ]
Komponente: scripts · Dateien: scripts/diagnostics.sh, scripts/tests/diagnostics_test.sh, CHANGELOG.md
Änderung: `host_rules` (`:100-129`): die Klammer-Auswahl (`:114-117`) gilt nur noch für `SMTP_FROM`, und dort je Postfach: der Wert wird nach dem Entfernen von Anzeigenamen in `"…"` an `,` geteilt, von jedem Postfach zählt der Inhalt von `<…>`, ohne Klammer das Postfach selbst; der Anzeigename bleibt wie bisher stehen. Die übrigen Host-Schlüssel werden an `,`, Leerraum, `<` und `>` geteilt, jedes Teil wird Regel (heute verschluckt eine Klammer den Rest des Werts). Ist `uname -n` ein Name mit Punkt, wird zusätzlich sein erstes Label Regel. Der Kommentar `:95-99` und der Kopf `:17-22` sagen es. Tests in `diagnostics_test.sh`, Fall (i) (`:320-366`) erweitert: `EXTRA_SANS=alt9.example.com <inner9.example.com> tail9.example.com` → alle drei Namen werden in Logzeilen `<host>`; `SMTP_FROM='"Ops9 Team" <ops9@mail.example.com>, dev9@mail.example.com'` → beide Adressen `<host>`, `Ops9 Team` bleibt; `uname -n` = `node9.corp.example.org` (Funktions-Stub wie `:254`) → `node9 started` wird `<host> started`, `node9.corp.example.org` wird `<host>`. Zuerst rot: `alt9`, `tail9`, `dev9` und `node9 started` (Probe am Stand 73bf0d31, Spec Problem 8). Die übrigen Erwartungen von (f) und (i) bleiben.
Verify: bash scripts/dev/verify.sh scripts --strict -- diagnostics_test
Doku: CHANGELOG.md (den Added-Eintrag `:12-20` anpassen, umlautfrei: jede Adresse eines Host-Werts, bei `SMTP_FROM` jede Adresse ohne Anzeigenamen, der Rechnername auch ohne Domain); die Doku-Sätze aus T4 bleiben richtig
Abhängt von: T8
Beweis: Code-Lesung scripts/diagnostics.sh:114-118, :123
HEAD: 73bf0d31

### T10 — diagnostics.sh `--mask-hosts`: IPv6 mit IPv4-Ende als eine Adresse, Image-Tags bleiben  [ ]
Komponente: scripts · Dateien: scripts/diagnostics.sh, scripts/tests/diagnostics_test.sh, CHANGELOG.md
Änderung: `host_rules` (`:103-109`) bekommt vor der IPv4-Regel (`:104`) eine Regel für IPv6 mit IPv4-Ende (bis zu sechs Hex-Gruppen mit `:` oder `::`, dann eine IPv4-Adresse, optional `/Präfix`); sie ergibt genau ein `<ip>`. Die IPv4-Regel lässt eine Zahlenfolge direkt hinter `<pfad>/<name>:` (Tag einer Image-Referenz) stehen. Tests in `diagnostics_test.sh`, Fall (f) (`:247-310`) erweitert: `::ffff:192.0.2.1`, `64:ff9b::198.51.100.7`, `2001:db8:1:2:3:4:192.0.2.1` und `0:0:0:0:0:ffff:203.0.113.5` werden je genau `<ip>`; `myreg:5000/adminhelper/server:0.46.0.1` bleibt; `connect to 192.0.2.9:5432` wird `connect to <ip>:5432`; die bestehenden Erwartungen von (f) (`[2001:db8::1]:8080`, `fe80::1`, `10:00:00`, `1.27.3`) bleiben. Zuerst rot: die vier IPv6-Formen (heute `<ip>:<ip>`, `<ip><ip>`, `2001:db8:1:2:3:4:<ip>`) und der Tag (`…/server:<ip>`).
Verify: bash scripts/dev/verify.sh scripts --strict -- diagnostics_test
Doku: CHANGELOG.md (den Added-Eintrag `:12-20` ergänzen, umlautfrei: IPv6-Adressen mit IPv4-Ende als eine Adresse; Image-Tags aus vier Zahlen bleiben)
Abhängt von: T9
Beweis: Code-Lesung scripts/diagnostics.sh:104-108
HEAD: 73bf0d31

### T11 — diagnostics.sh `--mask-hosts`: einteilige Namen nur als ganzes Wort, Namen samt Domain-Kette  [ ]
Komponente: scripts · Dateien: scripts/diagnostics.sh, scripts/tests/diagnostics_test.sh, CHANGELOG.md
Änderung: Regel-Bau in `host_rules` (`:124-128`): Ein Name ohne Punkt (etwa `uname -n` = `server`) trifft nur in seiner Schreibweise (ohne `I`), nicht hinter einem Zeichen aus `ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-`, nicht hinter `<Wortzeichen>/` und nicht vor einem Zeichen aus `ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-`; eine folgende Kette `.label` wird mit ersetzt (`node9.corp.example.org:443` → `<host>:443`). Ein Name mit Punkt trifft weiter ohne Rücksicht auf Groß-/Kleinschreibung (Ränder wie bisher) und ersetzt eine vorangehende Kette `label.` mit (`registry.ah.example.com:5000` → `<host>:5000`). Der Kommentar `:95-99` und der Kopf sagen es. Tests in `diagnostics_test.sh`, Fall (i) erweitert: mit `uname -n` = `server` bleiben `adminhelper-server-1 started`, `image ghcr.io/admincave/adminhelper/server:0.46.0` und `Server started`, `GET http://server:8443/` wird `GET http://<host>:8443/`, `server up` wird `<host> up`; mit `uname -n` = `node9` wird `node9.corp.example.org:443` `<host>:443`; mit `DOMAIN=ah.example.com` wird `registry.ah.example.com:5000` `<host>:5000`. Die bestehenden Erwartungen von (f) und (i) bleiben (`node9hostname up` bleibt, `AH.Example.com` maskiert `ah.example.com`). Zuerst rot: `adminhelper-server-1`, das Image, `Server started`, `node9.corp…` und `registry.ah…` (Probe am Stand 73bf0d31, Spec Problem 8).
Verify: bash scripts/dev/verify.sh scripts --strict -- diagnostics_test
Doku: CHANGELOG.md (den Added-Eintrag `:12-20` anpassen, umlautfrei: ohne Ruecksicht auf Gross-/Kleinschreibung gilt fuer Namen mit Punkt; ein Rechnername ohne Punkt nur in seiner Schreibweise und als ganzes Wort, nicht als Teil eines Dienst- oder Image-Namens)
Abhängt von: T10
Beweis: Code-Lesung scripts/diagnostics.sh:124-128
HEAD: 73bf0d31
