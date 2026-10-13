<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# URL-Helfer: lane_db und pg lesen AH_TEST_DB mit einer gemeinsamen Funktion — Task-Ledger
Status: aktiv · Branch: harness/pg-url-helper · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-13 (kleines Fund-Paket, Triage Kevin 2026-10-13; Fragen 1-3 wie empfohlen; Review am Ende Opus; Delegation Kevin 2026-10-05)
Spec: Kevin 2026-10-13 (Kurz-Ledger ohne Spec)
Heavy: none — ein gesourcter Shell-Helfer in `scripts/dev/`, `lane_db` in `lane.sh`, `pg` in `builder-home.sh` und ihre hermetischen Tests; kein Stack-, Gateway-, PKI- oder Install-Pfad.
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, SPDX bei neuen Dateien, Doku im selben Commit).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-13 von Worker B im Auftrag der Aufsicht (adminhelper-ac), angenommen von Kevin am 2026-10-13.
Zeilenangaben origin/main@1409c285. `scripts/dev/builder-home.sh` und `scripts/tests/builder_home_test.sh` sind
Harness-Pfade, und der neue Helfer wird einer. Den PR merged Kevin oder die Aufsicht auf sein Wort. Alle Werte in Tests
und Proben sind Platzhalter.

Zwei Funktionen zerlegen heute `AH_TEST_DB` des Haupt-Checkouts in eine URL für libpq und ein Passwort für
`PGPASSWORD`:
- `lane_db` in `scripts/dev/lane.sh` (`:74-169`; Prüfungen `:78-162`, Aufrufe `:163-168`) legt die Test-DB einer Lane an.
- `pg` in `scripts/dev/builder-home.sh` (`:105-157`; Prüfungen `:109-151`, Aufruf `:152-156`) legt die des Builders an.

Beide tragen eine eigene Kopie derselben Regeln, und die Kopien unterscheiden sich:
- `pg` dekodiert das Passwort mit `printf %b` (`:117`), `lane_db` wie `urllib.parse.unquote` (`lane.sh:95-114`).
- Nur `lane_db` lehnt eine URL ab, die kein UTF-8 ist (`:81-85`).

Dieses Ledger legt die Regeln in einen Helfer, den beide sourcen. Das Umschreiben des Schemas bleibt beim jeweiligen
Aufrufer:
- `lane_db_url` (`lane.sh:66-72`) macht nur aus `postgresql+<treiber>://` ein `postgresql://`.
- `pg` (`:111`) macht das auch aus `postgres://` und `postgres+<treiber>://`.

So bleiben die angenommenen Formen beider, wie sie sind.

### T1 — pg-url.sh: ein Helfer zerlegt eine Postgres-URL in URL und Passwort oder lehnt sie mit Grund ab  [ ]
Komponente: scripts · Dateien: scripts/dev/pg-url.sh, scripts/tests/pg_url_test.sh, scripts/tests/run.sh, scripts/dev/harness-paths.txt
Änderung:
- Neue Datei `scripts/dev/pg-url.sh` mit SPDX-Kopf (`reuse annotate --copyright "Kevin Stenzel" --license
  GPL-3.0-or-later`). Sie enthält nur Funktionen und ist zum Sourcen gedacht.
- `pg_url_split <url> <formen>` nimmt die URL so, wie der Aufrufer sie schon umgeschrieben hat.
  - Bei Erfolg setzt sie `PG_URL_OUT` (die URL ohne Passwort) und `PG_URL_PASS` (das Passwort, dekodiert), rc 0.
  - Bei Ablehnung setzt sie `PG_URL_ERR`, rc 1. Das ist der Grund, ohne Wert und ohne Programmnamen; den Präfix und den
    Exit setzt der Aufrufer. Die Meldung zur Allowlist bekommt `<formen>` angehängt: die Formen, die der Aufrufer annimmt.
- Inhalt sind die Prüfungen von `lane_db` (`lane.sh:81-162`), in derselben Reihenfolge und unter `local LC_ALL=C`:
  - UTF-8 der URL;
  - die Zerlegung, mit Merker;
  - die Dekodierung wie urllib: `%XX` mit zwei Hex-Ziffern wird zu dem Byte, jedes andere `%` bleibt. Ein NUL wird
    abgelehnt, ein Passwort, das nach der Dekodierung kein UTF-8 ist, ebenso;
  - die Prüfung eines Paars Nutzer:Passwort, das nicht zerlegt wurde (`:120-123`), und die nach der Lesart von SQLAlchemy
    (`:124-131`);
  - die drei Prüfungen der Query;
  - die Allowlist `postgresql://`.
  - Die Meldungen bleiben wörtlich. Nur die zu einem Geheimnis in der Query endet statt auf „lane.sh does not pass it on“
    auf „it is not passed on“; die Tests prüfen den Teil davor.
- `scripts/tests/pg_url_test.sh`, neu mit SPDX-Kopf und hermetisch, ist der gemeinsame Test-Satz: eine Tabelle von Fällen
  gegen `pg_url_split`.
  - Angenommen, je mit erwarteter URL und erwartetem Passwort:
    - ohne und mit Port;
    - IPv6;
    - `%40` im Passwort;
    - `/` und `:` im Passwort;
    - `%zz` und ein `%` am Ende bleiben stehen, `%41` wird `A`;
    - `%0a`;
    - `?application_name=a:b@c` hinter einem Port;
    - ohne Passwort.
  - Abgelehnt, je mit dem Grund:
    - eine URL, die kein UTF-8 ist;
    - `%00`;
    - `%ff`;
    - ein Nutzer mit eigenem `@`, auch mit `/` im Passwort;
    - ein leerer Nutzer;
    - `password`, `SSLPassword` und `pass%77ord` in der Query;
    - die Keyword-Form von libpq;
    - ein Schema ohne `//`.
  - Bei jeder Ablehnung steht der Platzhalter nicht in `PG_URL_ERR`.
  - Ein Fall unter GBK baut die Locale per `localedef` in den Testordner und setzt `LOCPATH` schon beim Start des
    Prozesses. Fehlt `localedef`, ist es ein `bad` mit Grund.
  - Für jeden angenommenen Fall wird `PG_URL_PASS` mit `python3 -c 'urllib.parse.unquote'` verglichen (Standardbibliothek,
    überall vorhanden).
- `scripts/tests/run.sh`: `pg_url_test` kommt in die Liste der Script-Tests (`:596-601`), neben `lane_test`.
- `scripts/dev/harness-paths.txt`: `scripts/dev/pg-url.sh` und `scripts/tests/pg_url_test.sh`, neben `builder-home.sh`
  (`:40`) und seinem Test (`:74`). `pg` wird den Helfer sourcen, er schreibt also mit an den Regeln des Builders.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern; die Regeln stehen im Kommentar des Helfers)
Beweis: origin/main@1409c285: `git ls-files scripts/dev/pg-url.sh` → kein Treffer. Die Zerlegung steht zweimal da,
`lane.sh:81-162` und `builder-home.sh:109-151`.
Orakel: differential — `PG_URL_PASS` gegen `urllib.parse.unquote` für jeden angenommenen Fall. Dazu mutation-sample: die
NUL-Prüfung im Helfer entfernt, dann wird der Fall `%00` rot.
Metrik: Kopien der Zerlegung von `AH_TEST_DB` im Repo: 2 → 1 (nach T3).
Dedup-Key: ref:scripts:lane.sh:shared-db-url-helper
HEAD: 1409c285
Semantik: `lane.sh:96-97`: „Decoded as urllib.parse.unquote does it, which SQLAlchemy uses: %XX with two hex digits
becomes that byte, every other % stays“. Dazu `builder-home.sh:101-104`: „The password travels in PGPASSWORD and not in an
argument … (lane.sh lane_db)“. Beide meinen dieselbe Regel.

### T2 — lane.sh: lane_db nimmt den Helfer  [ ]
Komponente: scripts · Dateien: scripts/dev/lane.sh, scripts/tests/lane_test.sh
Abhängt von: T1
Änderung:
- `lane.sh` sourct `scripts/dev/pg-url.sh`, neben `scripts/vm/lib.sh` (`:33`).
- `lane_db` ruft nach `lane_db_url` (`:80`) `pg_url_split "$url" "postgresql+<driver>:// counts as one"` auf. Bei rc ≠ 0
  folgt `echo "  lane.sh: $PG_URL_ERR" >&2; return 3`, wie bisher je Ablehnung.
- Die eigenen Prüfungen (`:81-162`) entfallen. `case "$1"` und die Aufrufe von `createdb`/`dropdb` (`:163-168`) nehmen
  `PG_URL_OUT` und `PG_URL_PASS`.
- `lane_test.sh`: Die Fixture kopiert den Helfer mit (`:64`). Sonst bleibt der Test, wie er ist, und alle seine Fälle
  bleiben grün: Ablehnungen, Dekodierung, GBK, Lesart von SQLAlchemy.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (`DEVELOPMENT.md:204-216` beschreibt das Verhalten von `lane.sh`, und das bleibt)
Beweis: origin/main@1409c285: `lane.sh:81-162` ist die Kopie, die T1 in den Helfer zieht.
Orakel: mutation-sample — im Helfer die Prüfung nach der Lesart von SQLAlchemy entfernt: die Fälle `pw-slash-at` und
`pw-slash-nouser` in `lane_test.sh` rot. Das zeigt, dass `lane_db` den Helfer nutzt.
Metrik: siehe T1.
Dedup-Key: ref:scripts:lane.sh:shared-db-url-helper
HEAD: 1409c285
Semantik: `DEVELOPMENT.md:209-210`: „kann `lane.sh` es dort nicht herauslösen, legt es keine Lane an“.

### T3 — builder-home.sh: pg nimmt den Helfer und liest das Passwort wie SQLAlchemy  [ ]
Komponente: scripts · Dateien: scripts/dev/builder-home.sh, scripts/tests/builder_home_test.sh, DEVELOPMENT.md
Abhängt von: T1
Änderung:
- `builder-home.sh` sourct `scripts/dev/pg-url.sh`, nach `ROOT=` (`:50`).
- `pg` ruft nach dem Umschreiben (`:111`) `pg_url_split "$url" "postgres:// and postgres(ql)+<driver>:// count as one"
  || fail "$PG_URL_ERR"` auf. Der Aufruf (`:152-156`) nimmt dann `PG_URL_OUT` und `PG_URL_PASS`.
- Die eigenen Prüfungen und die Dekodierung per `printf %b` (`:112-151`) entfallen. Damit dekodiert `pg` wie `lane_db` und
  lehnt dieselben Formen ab: eine URL, die kein UTF-8 ist, ein Passwort mit NUL und eines, das nach der Dekodierung kein
  UTF-8 ist.
- `builder_home_test.sh`: Die Fixture kopiert den Helfer mit (`:42-43`). Neue Fälle im Abschnitt „the database URL“:
  - `%zz` im Passwort → `PGPASSWORD` behält `%zz`;
  - `%00` → `setup` endet mit rc 1, kein `psql`/`createdb`;
  - eine URL mit einem Byte, das kein UTF-8 ist → rc 1.
  - Die bestehenden Fälle bleiben.
- `DEVELOPMENT.md:1226-1228`: ein Satz dazu. `setup` liest das Passwort wie SQLAlchemy und lehnt, wie `lane.sh`, eine URL
  ab, die kein UTF-8 ist.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md (Absatz zu `setup`)
Beweis: origin/main@1409c285. Die Probe (nicht committet, Platzhalter) zieht `fail`, `main_db_url` und `pg` aus
`builder-home.sh` und stellt eine aufzeichnende `createdb`-Attrappe davor:
- `…ah:PLACE%zzHOLDER@…` → `PGPASSWORD=PLACE\xzzHOLDER`; `urllib.parse.unquote` liest `PLACE%zzHOLDER`.
- `…ah:PLACE%00HOLDER@…` → `PGPASSWORD=PLACEHOLDER`, das NUL ist still verworfen; `lane_db` lehnt die Form ab.
- `…ah:PLACE<Byte 0xff>HOLDER@…` → rc 0; `lane_db` lehnt eine URL ab, die kein UTF-8 ist.
Orakel: mutation-sample — `pg` dekodiert wieder per `printf %b`: der Fall `%zz` rot.
Dedup-Key: bug:scripts:builder-home.sh:pg-percent-decode
HEAD: 1409c285
Semantik: `lane.sh:81`: „SQLAlchemy reads AH_TEST_DB as a UTF-8 string: a URL that is no UTF-8 is refused first.“ Dazu
`lane.sh:96-97` (siehe T1). `builder-home.sh:104` verweist für `pg` auf `lane_db`.
