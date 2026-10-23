<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Betriebsskripte, zweite Runde: Backup-Archiv robust am Zielnamen, Diagnose-Bundle liest die `.env` wie compose und maskiert genauer

Stand des Codes: `feature/ops-scripts-hardening@73bf0d31` (PR #266, zur Planung nicht gemergt). Der Branch
`feature/ops-scripts-2` steht absichtlich auf diesem Stand: das Vorhaben setzt die Arbeit von ops-scripts-hardening
fort und ändert dieselben Stellen. Alle `datei:zeile` beziehen sich auf 73bf0d31; der builder greppt sie vor dem
Schreiben neu. Ledger: `tasks/ops-scripts-2.md`. Roadmap R-0801 (T2) und R-0804 (T4); die übrigen Tasks gehören zum
Paket (Härtung, Kevin 2026-10-22).

## Problem / Motivation

1. **Backup-Archiv am Zielnamen (T1).** `scripts/backup.sh:138` benennt die fertige Zwischendatei mit
   `mv -f "$PARTIAL" "$ARCHIVE"` um. Ohne `-T` behandelt GNU `mv` ein Ziel, das ein Verzeichnis ist (oder ein Symlink
   auf eines), als Zielordner und legt das Archiv *hinein*; das Skript meldet trotzdem `OK -> <archiv>` (Name `:130`,
   Zeitstempel `:49`). Probe (GNU coreutils 9.7, dreimal identisch):
   ohne `-T` → Exit 0, die Datei liegt im Verzeichnis bzw. im Ziel des Symlinks; mit `mv -fT` → beim Verzeichnis Exit 1
   („cannot overwrite directory with non-directory“), beim Symlink wird der Link selbst durch das Archiv ersetzt.
   `scripts/update.sh:495`, `:520`, `:611` nutzen schon `mv -fT`.

2. **Backup: Daten vor dem Umbenennen auf der Platte, `--help` ohne Code (R-0801, T2).** Zwischen `tar` (`:137`) und
   `mv` (`:138`) steht kein `sync`: nach einem Stromausfall kann der endgültige Name auf eine leere oder gekürzte Datei
   zeigen, obwohl ops-scripts-hardening genau das ausschließen sollte (Kommentar `:131-135`). `--help` (`:37`) druckt
   `sed -n '2,30p'`, also hinter der Usage-Zeile (`:23`) auch `set -euo pipefail`, `umask 077` und `OUT_DIR="./backups"`
   (`:25-30`).

3. **`env.sanitized` im Backup (T3).** Der Filter `backup.sh:111` entfernt `CA_ROOT_PASSPHRASE` in den Schlüssel-Formen
   `export`, Leerraum um den Trenner, `=` oder `:`. Stehen bleiben: eine auskommentierte Zeile
   (`#CA_ROOT_PASSPHRASE=…`, etwa nachdem man den Wert nach dem ersten Start nicht mehr braucht), eine Zeile mit BOM
   oder Unicode-Leerraum vor dem Schlüssel (compose liest beide, Probe unten) und die Folgezeilen eines mehrzeiligen
   Werts in Anführungszeichen. Das Archiv soll die Passphrase in keiner Form tragen (Kopf `:16-20`).

4. **Wortlaut zu `SMTP_FROM` (R-0804, T4).** Kopf `scripts/diagnostics.sh:17-22`, `docs/admin/troubleshooting.html:147`,
   `docs/en/admin/troubleshooting.html:135` und `README.md:309` sagen, mit `--mask-hosts` würden „die Namen und
   Adressen“ aus `SMTP_FROM` maskiert. Maskiert wird nur die Adresse in spitzen Klammern, der Anzeigename nicht
   (`host_rules`, `:114-117`; gewollt, Fall (i) in `scripts/tests/diagnostics_test.sh:331-365`). Der CHANGELOG-Eintrag
   (`CHANGELOG.md:15`) sagt es schon richtig.

5. **`SMTP_USER` (T5).** `SMTP_USER` steht unter den Host-Schlüsseln (`diagnostics.sh:54`) und bleibt ohne
   `--mask-hosts` im Bundle stehen. Bei manchen Mail-Anbietern ist der SMTP-Benutzer selbst ein Zugangs-Token oder eine
   Key-ID; er gehört zu den Zugangsdaten wie `SMTP_PASSWORD` (`SECRET_KEYS`, `:49`).

6. **Die `.env` so lesen, wie compose sie liest (T6, T7).** `env_values` (`:137-142`) und `sanitize_env` (`:183-196`)
   erkennen einen Schlüssel nur hinter ASCII-Leerraum am Zeilenanfang; `env_value_forms` (`:152-165`) dekodiert keine
   Escapes und liest jeden Wert einzeilig. Compose liest mehr (Doku und Probe unter „Externe Integrationen“):
   - BOM am Dateianfang und Unicode-Leerraum (NBSP, EM SPACE …) vor dem Schlüssel; die Werte solcher Zeilen bleiben
     heute in den Logs und in `env.sanitized` stehen (Probe: `SECRET_KEY`, `POSTGRES_PASSWORD`, `MONITOR_API_KEY`);
   - in doppelten Anführungszeichen `\"`, `\\`, `\t`, `\n` …, in einfachen `\'`; der Wert endet am ersten *nicht*
     maskierten Anführungszeichen. Heute schneidet `:159` am ersten `"`, Werte mit einem dieser Zeichen werden in den
     Logs nicht gefunden (Probe: `ab"cd9esc`, `pq\9bs`, `sq'9sq` bleiben stehen);
   - Werte in Anführungszeichen über mehrere Zeilen; heute bleiben beide Teile in den Logs und die Folgezeilen in
     `env.sanitized` stehen;
   - Leerraum um den Wert: zwischen Trenner und Wert überspringt compose auch NEL und NBSP, am Ende eines Werts ohne
     Anführungszeichen schneidet es jeden Leerraum nach `unicode.IsSpace` ab; in Anführungszeichen bleibt Leerraum
     Teil des Werts. Das Bundle maskiert die Werte so, wie compose sie liest (T7, Session 2026-10-23).
   Dazu bleiben auskommentierte Zeilen eines Secret-Schlüssels (`#ADMIN_PASSWORD=…`) in `env.sanitized` stehen.

7. **Das Bundle selbst (T8).** `diagnostics.sh:262` schreibt das Bundle mit `tar -czf` direkt unter seinem Namen und mit
   der umask des Aufrufers (meist 0644); eine schon vorhandene Datei dieses Namens wird überschrieben und behält Besitz
   und Modus. `sanitize_env` übergibt die Host-Regeln von `--mask-hosts` als Argument an `sed` (`:191`, `:195`); damit
   stehen Domain, SANs und Adressen für die Laufzeit in der Prozessliste, also genau die Werte, die der Schalter
   verbergen soll.

8. **`--mask-hosts` genauer (T9–T11).** Proben am Stand 73bf0d31 (`source scripts/diagnostics.sh`, dreimal identisch):
   - eine Klammer `<…>` in einem Host-Wert verschluckt den Rest: aus
     `EXTRA_SANS=alt9.example.com <inner9.example.com> tail9.example.com` wird nur `inner9.example.com` eine Regel;
     bei `SMTP_FROM` mit zwei Adressen nur die erste (`:114-117`);
   - IPv6-Adressen mit IPv4-Ende werden in Stücken maskiert: `::ffff:192.0.2.1` → `<ip>:<ip>`,
     `2001:db8:1:2:3:4:192.0.2.1` → `2001:db8:1:2:3:4:<ip>`, `64:ff9b::198.51.100.7` → `<ip><ip>` (die IPv4-Regel `:104`
     läuft vor den IPv6-Regeln `:105-108`);
   - ein kurzer Rechnername trifft Dienst- und Image-Namen und gewöhnliche Wörter: mit `uname -n` = `server` wird
     `adminhelper-server-1` zu `adminhelper-<host>-1`, `ghcr.io/admincave/adminhelper/server:0.46.0` zu
     `…/<host>:0.46.0`, `Server started` zu `<host> started` (Regel mit `gI`, `\b` erlaubt `-` und `/` als Rand); ein
     Image-Tag aus vier Zahlen wird `<ip>` (`myreg:5000/adminhelper/server:1.2.3.4` → `…/server:<ip>`);
   - Rechnername und Domain: bei `uname -n` = `node9` bleibt aus `node9.corp.example.org:443` die Domain stehen
     (`<host>.corp.example.org:443`); bei einem FQDN als Rechnername bleibt der kurze Name `node9` stehen; mit
     `DOMAIN=ah.example.com` wird `registry.ah.example.com` zu `registry.<host>`.

## Ziel & Nicht-Ziele

**Ziel:**
- Das Backup-Archiv liegt nach Exit 0 genau unter seinem Namen als Datei, seine Daten sind vor dem Umbenennen auf der
  Platte; `--help` druckt nur den Kommentarkopf (T1, T2).
- `env.sanitized` im Backup trägt `CA_ROOT_PASSPHRASE` in keiner Zeilenform, die compose liest oder die auskommentiert
  ist (T3).
- Kopf, `--help`, Doku und README sagen bei `SMTP_FROM` genau, was maskiert wird (T4).
- `SMTP_USER` wird immer maskiert wie die übrigen Zugangsdaten (T5).
- Das Diagnose-Bundle findet die Secrets der `.env` in den Formen, die compose liest: BOM, Unicode-Leerraum vor dem
  Schlüssel und um den Wert, Escapes, mehrzeilige Werte; `env.sanitized` maskiert auch auskommentierte Zeilen dieser
  Schlüssel (T6, T7).
- Das Bundle ist vom ersten Byte an 0600 und trägt seinen Namen erst vollständig; keine Host-Werte in der Prozessliste
  (T8).
- `--mask-hosts` maskiert jede Adresse eines Host-Werts, IPv6 mit IPv4-Ende als ein `<ip>`, den Rechnernamen kurz und
  lang samt Domain-Suffix und Namen unter einer maskierten Domain ganz, ohne Dienst-, Image- und gewöhnliche Wörter zu
  treffen (T9–T11).

**Nicht-Ziele:**
- **`scripts/pg-backup.sh` braucht kein zusätzliches `sync`** (R-0801, zweiter Teil): `pg_dump` schreibt die Datei
  selbst (`scripts/pg-backup.sh:25`, `:29`, `--file=…dump.tmp`) und wartet nach der PostgreSQL-Doku standardmäßig, bis
  sie sicher auf der Platte ist („By default, pg_dump will wait for all files to be written safely to disk“,
  abschaltbar mit `--no-sync`); im Quelltext REL_17_STABLE `src/bin/pg_dump/pg_backup_custom.c`, `_CloseArchive`:
  `fsync_fname(AH->fSpec, false)`. Der Dienst nutzt `postgres:17-alpine` (`docker-compose.yml:428-440`). Das `mv`
  (`:26`, `:30`) benennt also eine schon gesyncte Datei um. Keine Task.
- **Eine Passphrase-Datei des ca-issuer im Backup:** die ausgelieferte `docker-compose.yml` übergibt dem ca-issuer nur
  `CA_ROOT_PASSPHRASE` (`:233`), keine `CA_ROOT_PASSPHRASE_FILE`; `backup.sh:87` sichert nur `/app/data`. Keine Task
  (Offene Frage 1).
- `--mask-hosts` bleibt ein Schalter (Kevin 2026-10-22); kein Opt-out für `SMTP_USER` (Offene Frage 2).
- Keine gemeinsame Bibliothek für backup.sh und diagnostics.sh: zwei Skripte, ein Filter je Skript (YAGNI).
- Kein Maskieren von Namen außerhalb der `.env`-Schlüssel und des Rechnernamens (verwaltete Server, Webhook-Ziele);
  die Redaction bleibt Best-effort, Kopf und Doku sagen es.

## Betroffene Komponenten & Dateien

Komponente `scripts` (verify.sh-Name) für alle Tasks.
- `scripts/backup.sh`, `scripts/tests/restore_guard_test.sh` (T1–T3, Abschnitt backup.sh ab `:178`)
- `scripts/diagnostics.sh`, `scripts/tests/diagnostics_test.sh` (T4–T11)
- `docs/admin/troubleshooting.html`, `docs/en/admin/troubleshooting.html`, `README.md` (T4, T5, T8)
- `CHANGELOG.md` (T1–T3, T5–T11)

Nicht berührt: `scripts/install.sh`, `scripts/update.sh`, `scripts/agent-install.sh` (update.sh ruft backup.sh nur auf,
`scripts/update.sh:363`, `:438`), `docker-compose.yml`, `apps/*`, `scripts/tests/run.sh`, `.github/workflows/`.

Überschneidungen mit anderen Vorhaben (Dateien, je auf ihrem Branch):
- install-restore (freigegeben): `scripts/tests/restore_guard_test.sh` (dort T5, T6, Abschnitt restore.sh),
  `docs/admin/troubleshooting.html` + EN (dort T2, Abschnitt Installation `:38-46`), `CHANGELOG.md`; dort heißt es
  „Bau nach … ops-scripts-hardening“ — dieses Vorhaben gehört in dieselbe Reihe.
- docs-drift (aktiv): `docs/admin/troubleshooting.html` + EN (Agent-Abschnitte), `CHANGELOG.md`.
- ops-install-hardening (aktiv): `README.md` (dort T4, `:176`), `CHANGELOG.md`.
- compose-hardening, update-rollback, ca-issuer-lifetime: nur `CHANGELOG.md`.

## Datenmodell / API / Migrationen

Keine. Kein API-Vertrag, keine Migration. Sichtbar ändern sich: der Inhalt von `env.sanitized` im Backup (T3) und im
Diagnose-Bundle (T5–T7), der Modus des Bundles (T8) und was `--mask-hosts` maskiert (T9–T11).

## Externe Integrationen

- **Docker Compose, `.env`-Syntax:** https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/
  (gelesen 2026-10-22): `=` oder `:` als Trenner, Leerraum um den Wert wird ignoriert; unquotiert beginnt ein Kommentar
  mit ` #`; einfache Anführungszeichen wörtlich, „Quotes can be escaped with `\`“ (`'Let\'s go!'` → `Let's go!`);
  „Common shell escape sequences including `\n`, `\r`, `\t`, and `\\` are supported in double-quoted values“;
  „Single-quoted values can span multiple lines“. Der Parser von compose-go (`dotenv/parser.go`) dekodiert in doppelten
  Anführungszeichen `\a \b \f \n \r \t \v \$ \" \\` und Oktal `\0nnn`, überspringt führenden Leerraum mit
  `unicode.IsSpace` und lässt auch doppelt gequotete Werte über Zeilen laufen. Probe Docker Compose v5.5.1,
  `docker compose config --format json`: `A="ab\"cd"` → `ab"cd`; `B="a\\b"` → `a\b`; `C='Let\'s go'` → `Let's go`;
  `D='multi⏎line'` und `E="dq⏎multi"` → Wert mit Zeilenumbruch; `G="tab\there"` → echter Tab; NBSP und EM SPACE vor dem
  Schlüssel → gelesen; BOM am Dateianfang → gelesen; `#H=` → Kommentar. Probe derselben Version (2026-10-23, T7):
  NBSP und NEL zwischen Trenner und Wert → übersprungen, auch vor einem Anführungszeichen; NBSP, NEL und EM SPACE am
  Ende eines Werts ohne Anführungszeichen → abgeschnitten; NBSP in Anführungszeichen → Teil des Werts; `"\0351"` →
  `é` als UTF-8, ein `\0` ohne drei Oktalziffern verliert die `0` (`"\08"` → `\8`); `\c` und `\x` bleiben wörtlich.
- **GNU coreutils 9.7:** `mv -T, --no-target-directory` (Ziel als normale Datei behandeln); `sync [OPTION] [DATEI]…`
  synchronisiert mit Dateiargumenten nur diese (`sync --help`).
- **pg_dump (PostgreSQL 17):** https://www.postgresql.org/docs/17/app-pgdump.html, Option `--no-sync` (siehe
  Nicht-Ziele).

## Trade-offs & Alternativen

1. **T1: `mv -fT` statt Vorprüfung.** Eine Prüfung `[ -e "$ARCHIVE" ]` vor dem `mv` ließe ein Zeitfenster; `-T` macht
   die Umbenennung selbst eindeutig. Ein vorhandenes Verzeichnis unter dem Namen bricht das Backup ab (Exit ≠ 0,
   Zwischendatei weg), ein Symlink wird ersetzt. Empfehlung: `-T`, wie in `update.sh`.
2. **T2: `sync -- <datei>` und danach `sync -- <ordner>`** statt eines globalen `sync` (würde jedes Dateisystem des
   Hosts flushen). Kostet bei großen Archiven die Zeit, bis die Daten geschrieben sind — die braucht ein Backup ohnehin.
3. **T5: `SMTP_USER` als Secret, Wertregel an Wortgrenzen.** Ohne Wortgrenze würde ein kurzer Benutzer wie `admin`
   in `adminhelper` hineinbeißen; mit `\b` an Rändern aus Wortzeichen wird nur das ganze Wort maskiert. Nur für
   `SMTP_USER`: die übrigen Secrets sind lang und zufällig. Folge: ein Benutzername, der ein gewöhnliches Wort ist,
   wird als Wort überall `<redacted>` (sichere Richtung).
4. **T7: jede Zeile eines mehrzeiligen Werts wird eine eigene Regel** (eine Logzeile trägt höchstens eine Zeile des
   Werts), außer einer aus reinem Leerraum: sie trägt kein Geheimnis. Eine kurze Zeile maskiert dann auch Fremdes
   (sichere Richtung). Alternative „nur Zeilen ab n Zeichen“ ließe kurze Teile stehen; verworfen.
5. **T8: Zwischendatei im Zielordner + `mv -fT`** statt nur `umask 077`: die umask wirkt nicht auf eine Datei, die
   unter dem Namen schon liegt. Die Zwischendatei legt erst das Schreiben an, exklusiv und mit 0600 (Name von
   `mktemp -u`, `tar` schreibt in eine Pipe, `dd conv=excl` legt die Datei an); liegt unter ihrem Namen schon etwas,
   auch ein Link, endet der Lauf mit Fehler. Unter `sudo` gehört das Bundle dann root mit 0600 (Doku-Satz).
6. **T11: einteilige Namen case-sensitiv und mit strengerem Rand.** Ein Rechnername ohne Punkt ist oft ein gewöhnliches
   Wort oder ein Dienstname. Er wird nur noch getroffen, wenn er nicht Teil eines mit `-`, `.`, `_` verbundenen Worts
   oder eines Pfadsegments (`…/server:`) ist, und nur in der Schreibweise von `uname -n`. Namen mit Punkt bleiben
   ohne Rücksicht auf Groß-/Kleinschreibung (ops-scripts-hardening T6). Folge: `NODE9` in Großbuchstaben bleibt stehen,
   wenn der Rechner `node9` heißt; Kopf und Doku sagen ohnehin „Best-effort, durchsehen“.
7. **T10: Image-Tag statt IPv4.** Eine Folge aus vier Zahlen direkt hinter `<pfad>/<name>:` gilt als Image-Tag und bleibt.
   Eine Adresse in genau dieser Schreibweise bliebe damit stehen; in den Logs des Stacks stehen Adressen hinter
   Leerraum, `=`, `[`, `(` oder `//`.

## Risiken & Rollback

- Über-Maskierung macht ein Bundle schwerer lesbar (T5, T7, T11 setzen bewusst Grenzen); Unter-Maskierung bleibt
  möglich, die Abschlussmeldung und die Doku sagen „durchsehen“.
- T3 ändert, welche Zeilen `env.sanitized` im Backup hat; `restore.sh` legt daraus `.env.restored` an. Entfernt werden
  nur Zeilen des Schlüssels `CA_ROOT_PASSPHRASE` (auch auskommentiert) und die Folgezeilen seines Werts.
- `backup_restore_test.sh` (`run.sh integration`, `scripts/tests/run.sh:893`) fährt backup.sh real; `update.sh` ruft es
  vor jedem Update. Darum `Heavy: linux-full` (Ledger).
- Rollback: Revert der Task-Commits; kein Zustand außerhalb der Skripte.

## Doku-Impact

DE + EN: `docs/admin/troubleshooting.html` / `docs/en/admin/troubleshooting.html` (Abschnitt Diagnose-Bundle: Wortlaut
`SMTP_FROM`, `SMTP_USER` bei den Zugangsdaten, Bundle 0600) und `README.md:309`. `docs/admin/betrieb.html` bleibt
(Backup-Verhalten ohne neue Nutzerschritte). CHANGELOG je Task, umlautfrei; solange die Einträge von
ops-scripts-hardening unter `[Unreleased]` stehen, passen die Tasks diese an, statt doppelte Einträge zu schreiben.

## Offene Fragen

1. **Passphrase-Datei in einem eigenen Compose-Override im Volume `ca-pki`.** Nur ein selbst gebautes Override
   könnte `CA_ROOT_PASSPHRASE_FILE` auf einen Pfad unter `/app/data` legen; dann sicherte backup.sh die Datei mit.
   Optionen: (a) keine Task (Empfehlung: die ausgelieferte Konfiguration ist nicht betroffen; nach compose-hardening
   T6 liegt die Datei unter `/run/secrets`); (b) backup.sh fragt den ca-issuer nach `CA_ROOT_PASSPHRASE_FILE` und
   lässt eine Datei unter `/app/data` mit Warnung und MANIFEST-Zeile aus dem Archiv (erst nach compose-hardening T5
   sinnvoll, sonst startet ein restaurierter ca-issuer ohne die Datei nicht, `apps/ca-issuer/app/config.py:51-53`);
   (c) Abbruch des Backups (blockiert `update.sh`). Keine Task hängt daran.
2. **Opt-out für `SMTP_USER`.** Empfehlung: keins. Ein Schalter wäre neue Oberfläche für einen Wert, den ein
   Bug-Report selten braucht; `SMTP_HOST` und `SMTP_FROM` bleiben ohne `--mask-hosts` sichtbar. Keine Task hängt daran.
