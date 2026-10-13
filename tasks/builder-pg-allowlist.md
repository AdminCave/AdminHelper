<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# builder-home.sh: pg nimmt nur postgresql://-URLs und liest sie unter C — Task-Ledger
Status: aktiv · Branch: harness/builder-pg-allowlist · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-13 (kleines Fund-Paket, Triage Kevin 2026-10-13; T3 bleibt drin; Delegation Kevin 2026-10-05)
Freigabe T4: Aufsicht adminhelper-ac, 2026-10-13 (Erweiterung auf Kevins Wort 2026-10-13)
Spec: Kevin 2026-10-13 (Kurz-Ledger ohne Spec)
Heavy: none — `pg` in `scripts/dev/builder-home.sh` und sein hermetischer Test; kein Stack-, Gateway-, PKI- oder Install-Pfad.
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, Doku im selben Commit).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-13 von Worker B im Auftrag der Aufsicht (adminhelper-ac), angenommen von Kevin am 2026-10-13.
Zeilenangaben origin/main@b57c2813. `scripts/dev/builder-home.sh` und `scripts/tests/builder_home_test.sh` sind
Harness-Pfade; den PR merged Kevin oder die Aufsicht auf sein Wort. Alle Werte in Tests und Proben sind Platzhalter.

`pg` (`builder-home.sh:105-121`) ruft für `setup` (`:250-252`) `psql` und `createdb` auf dem Server auf, den
`AH_TEST_DB` des Haupt-Checkouts nennt. Es macht aus `postgres://` und `postgresql+<treiber>://` ein `postgresql://`
(`:107`), löst das Passwort heraus (`:108-113`) und prüft danach eine Form (`:115`). `lane_db` in `scripts/dev/lane.sh`
(`:74-160`) tut dasselbe für die Test-DB einer Lane und prüft mehr. Dieses Ledger bringt `pg` auf dieselben Regeln.

### T1 — pg: nur eine URL, die mit `postgresql://` beginnt, erreicht psql/createdb  [x]
Komponente: scripts · Dateien: scripts/dev/builder-home.sh, scripts/tests/builder_home_test.sh, DEVELOPMENT.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @4317d020 2026-10-13T10:52:09+02:00
Review: Review am Ende (Kurz-Ledger, Opus)
Änderung:
- `pg`: Nach der Prüfung `:115` und vor dem Aufruf (`:116`) nimmt die Funktion nur noch eine URL an, die mit
  `postgresql://` beginnt. Nach `:107` gilt das auch für `postgres://` und `postgresql+<treiber>://`. Jede andere Form
  endet mit `fail` und einer Meldung ohne Wert, wie die Ablehnung in `:115`. Die bestehende Prüfung und ihre Meldung
  bleiben.
- `builder_home_test.sh`, Abschnitt „the database URL“ (`:269-284`): neue Fälle nach dem Muster von `:280-283`.
  Zwei Formen ohne `postgresql://` ergeben je: rc 1, die Meldung, keine Zeile `psql` oder `createdb` im Log der
  Attrappen, der Platzhalter des Passworts in keiner Ausgabe.
  - die Keyword-Form von libpq (`host=… user=… password=… dbname=…`);
  - `postgresql+psycopg:` ohne `//`.
- Die bestehenden Fälle mit `postgres://` und `postgresql+psycopg://` bleiben grün.
- `DEVELOPMENT.md` (`:1225`, „eine eigene Test-DB `adminhelper_builder` auf dem Server des Haupt-Checkouts“): ein Satz
  dazu. Wie `lane.sh` nimmt `setup` dafür nur eine URL `postgresql://`, `postgres://` oder `postgresql+<treiber>://`;
  eine andere Form, etwa die Keyword-Form von libpq, lehnt es ab.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md (Absatz zu `setup`)
Beweis: origin/main@b57c2813. Die Probe (nicht committet, Platzhalter) zieht `fail`, `main_db_url` und `pg` aus
`builder-home.sh` und stellt eine aufzeichnende `createdb`-Attrappe davor. Zwei Formen ohne `postgresql://` erreichen
den Aufruf von `createdb`, je mit rc 0:
- `host=db.invalid user=ah password=… dbname=adminhelper_test`;
- `postgresql+psycopg:ah:…@db.invalid/adminhelper_test`.
Orakel: mutation-sample — die neue Prüfung entfernt: die neuen Fälle in `builder_home_test.sh` rot.
HEAD: b57c2813
Semantik: `builder-home.sh:101-104`: „pg psql|createdb <args…> — on the server of the main checkout's AH_TEST_DB,
connected to that database, with its credentials. The password travels in PGPASSWORD and not in an argument … (lane.sh
lane_db).“ Was nicht die Form hat, die `:107` herstellt, ist keine, die `pg` kennt.

### T2 — pg liest die URL byteweise, unabhängig von der Locale des Aufrufers  [x]
Komponente: scripts · Dateien: scripts/dev/builder-home.sh, scripts/tests/builder_home_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @8846e977 2026-10-13T11:06:39+02:00
Review: Review am Ende (Kurz-Ledger, Opus)
Abhängt von: T1
Änderung:
- `pg` setzt am Anfang `local LC_ALL=C`, wie `lane_db` (`lane.sh:75-78`). Die Muster der Funktion lesen damit Bytes,
  auch unter einer Mehrbyte-Locale des Aufrufers.
- `builder_home_test.sh`: ein Fall unter GBK, nach dem Muster von `lane_test.sh:171-191`.
  - `localedef -i zh_CN -f GBK` baut die Locale in den Testordner. `LOCPATH` muss schon beim Start des Prozesses
    stehen (`/usr/bin/env LOCPATH=… LC_ALL=…`), denn glibc liest es aus der Umgebung des Prozesses.
  - URL: Platzhalter, ein Zeichen wie `中` direkt vor `@`.
  - Erwartet: `setup` übergibt `psql` und `createdb` unter `zh_CN.GBK` dieselbe URL und dasselbe `PGPASSWORD` wie unter
    `LC_ALL=C`. Verglichen werden die Zeilen im Log der Attrappen.
- Kann `localedef` die Locale nicht bauen, ist der Fall ein `bad` mit Grund, kein stilles Grün.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern)
Beweis: origin/main@b57c2813. Dieselbe Probe, dieselbe Attrappe. Die URL
`postgresql+psycopg://ah:…中@db.invalid/adminhelper_test` ergibt für `createdb` unter `zh_CN.GBK` (per `localedef` in
einen eigenen Ordner gebaut, `LOCPATH`) eine andere URL als unter `LC_ALL=C`.
Orakel: mutation-sample — `local LC_ALL=C` entfernt: der GBK-Fall rot.
HEAD: b57c2813
Semantik: `lane.sh:75-77`: „Bytes, not the caller's characters: the patterns below must find the same @ and : under any
locale, and a multibyte one can read a byte after a character as part of it.“ `pg` folgt `lane_db` (`builder-home.sh:104`).

### T3 — pg lehnt ab, was lane_db ablehnt: einen Nutzer mit @ vor dem Passwort, ein Geheimnis in der Query  [x]
Komponente: scripts · Dateien: scripts/dev/builder-home.sh, scripts/tests/builder_home_test.sh, DEVELOPMENT.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @66324a99 2026-10-13T12:15:19+02:00
Review: Review am Ende (Kurz-Ledger, Opus)
Abhängt von: T1
Änderung:
- Die Prüfung `:115` nimmt die Form von `lane.sh:119`: Der Teil vor dem Passwort darf ein eigenes `@` tragen
  (`[^/]*` statt `[^/@]*` vor dem `:`). Die Meldung von `:115` bleibt.
- Nach ihr die drei Prüfungen der Query aus `lane.sh:123-145`, je mit `fail` und einer Meldung ohne Wert:
  - `password=` in der Query;
  - die Schlüssel `sslpassword`, `oauth_client_secret`, `scram_client_key`, `scram_server_key` und `password` in jeder
    Schreibweise;
  - ein Prozentzeichen in einem Schlüssel der Query.
- `builder_home_test.sh`, im selben Abschnitt: Je ergibt rc 1, keine Zeile `psql` oder `createdb` im Log, der
  Platzhalter in keiner Ausgabe.
  - `postgresql://ah@corp:…@localhost/adminhelper_test`;
  - `postgresql://ah@localhost/adminhelper_test?password=…`;
  - `?SSLPassword=…`;
  - `?pass%77ord=…`.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern; `DEVELOPMENT.md` nennt nach T1 die angenommenen Formen)
Beweis: origin/main@b57c2813. Dieselbe Probe, dieselbe Attrappe. Zwei Formen erreichen den Aufruf von `createdb`, je mit
rc 0:
- `postgresql://ah@corp:…@db.invalid/adminhelper_test`;
- `postgresql://ah@db.invalid/adminhelper_test?password=…`.
Orakel: mutation-sample — die Prüfung `:115` auf die alte Form zurückgesetzt bzw. die Query-Prüfungen entfernt: die
neuen Fälle rot.
HEAD: b57c2813
Semantik: `builder-home.sh:114`: „A user:password the pattern did not take apart would go into an argument.“ Dazu
`lane.sh:115-118` und `:123-124`: „The part before the password may hold an @ of its own: SQLAlchemy reads
ah@corp:<password>@host as user ah@corp, the pattern above does not“ und „libpq takes ?password= too, and it would reach
the arguments the same way“.

### T4 — lane_db: wo das Muster nichts zerlegt hat, lehnt es auch die Lesart von SQLAlchemy ab  [ ]
Komponente: scripts · Dateien: scripts/dev/lane.sh, scripts/tests/lane_test.sh
Änderung:
- `lane_db` (`lane.sh:74-160`) merkt sich, ob das Muster in `:92` die URL zerlegt hat.
- Hat es nichts zerlegt, lehnt `lane_db` nach der Prüfung `:119-122` auch eine URL ab, in der SQLAlchemy ein Passwort
  liest. SQLAlchemy liest den Nutzer bis zum ersten `:` und das Passwort bis zum ersten `@`, auch über `/` hinweg
  (`^[^/]*//[^:/]*:[^@]*@`). Meldung und Code sind die von `:120-121` (`return 3`, kein Wert).
- Nach einer Zerlegung ist das erste `@` verbraucht. Ein `@` weiter hinten, etwa in der Query hinter einem Port, bleibt
  erlaubt; das deckt der bestehende Fall „phi“ (`lane_test.sh:290`).
- `pg` in `builder-home.sh` bekommt dieselbe Prüfung als Nachbesserung zu T3, aus dem Review am Ende.
- `lane_test.sh`: ein neuer Block nach dem von `:138-152`. Zwei Formen mit einem `/` im Passwort ergeben je: rc 1,
  kein Aufruf von `createdb`, keine Lane, keine Marke, die Meldung, und der Platzhalter in keiner Ausgabe.
  - ein Nutzer mit eigenem `@`;
  - ein leerer Nutzer.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (`DEVELOPMENT.md:209-210`: „kann `lane.sh` es dort nicht herauslösen, legt es keine Lane an“ deckt die Form)
Beweis: origin/main@c37d4198. Die Probe (nicht committet, Platzhalter) zieht `lane_db_name`, `lane_db_url` und `lane_db`
aus `lane.sh` und stellt eine aufzeichnende `createdb`-Attrappe davor. Zwei Formen erreichen den Aufruf von `createdb`,
je mit rc 0:
- `postgresql+psycopg://ah@corp:…/…@db.invalid/adminhelper_test`;
- `postgresql+psycopg://:…/…@db.invalid/adminhelper_test`.
Orakel: mutation-sample — die neue Prüfung entfernt: die zwei neuen Fälle in `lane_test.sh` rot.
HEAD: c37d4198
Semantik: `lane.sh:89-91`: „The password runs to the first @, across a /, the way SQLAlchemy reads AH_TEST_DB
(sqlalchemy/engine/url.py): a password the suites take out of the URL is one lane_db takes out too“. Dazu `:115-116`: „A
user:password the pattern did not take apart would go into an argument unchanged: stop before either program runs“.
