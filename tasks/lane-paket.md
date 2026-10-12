<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness-Kleinpaket lane.sh: Passwort in der Query, Gruppe über `/`, Meldung bei Exit 3 (R-0265, R-0266, R-0269) — Task-Ledger
Status: bereit · Branch: harness/lane-paket · Commit-Granularität: pro Task · Review: am Ende (Opus) · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-12 (kleines Fund-Paket aus R-0265, R-0266, R-0269, Triage Kevin 2026-10-10; R-0265 geschlossen fehlschlagen wie R-0255; Proben nur mit Platzhalter; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0265, R-0266, R-0269 (Kurz-Ledger ohne Spec)
Heavy: none — scripts/dev/lane.sh mit dem hermetischen lane_test (Fake-createdb/-dropdb); kein Stack-, Gateway-, PKI- oder Install-Pfad.
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-12 von Worker A für die Aufsicht (adminhelper-ac). Kevin hat die drei Zeilen am 2026-10-10 als
Harness-Kleinpaket lane.sh angenommen. Zeilenangaben origin/main@40d3eb0a; beim Bau an Symbolen orientieren.

Vorab geprüft:
- R-0265 und R-0266 liegen in derselben Funktion (`lane_db`, :74–99) und im selben Abschnitt von lane_test (:135–148,
  „a URL whose password lane.sh cannot take out makes no lane“). Sie sind eine Task (T1), R-0269 ist T2. Zwei Tasks
  reichen.
- Proben in diesem Plan und im Bau nur mit dem Platzhalter `secret` aus lane_test, nie mit einem echten Passwort.
  Meldungen nennen nie die URL („DB-URL in Fehlermeldungen“). Die bestehende Prüfung `! grep -q secret` gilt auch für
  jeden neuen Fall.
- R-0265, Empfehlung: geschlossen fehlschlagen, nicht den Wert nach `PGPASSWORD` holen.
  - Der Weg ist derselbe wie für R-0255: Exit 3 mit eigener Meldung, keine Lane.
  - Das Herauslösen aus der Query müsste dekodieren und den Parameter samt `&` sauber entfernen. Das ist mehr
    Parser-Code an einer Stelle, die ein Passwort trägt, für eine Form, die `.devenv.sh` nicht schreibt (dort steht
    `Benutzer:Passwort@`).
  - Die Meldung sagt, wie es geht (`Benutzer:Passwort@` vor den Host), und nennt die URL nicht.

### T1 — lane_db: keine Gruppe über `/`, kein Passwort in der Query (R-0266, R-0265)  [x]
Komponente: scripts · Dateien: scripts/dev/lane.sh, scripts/tests/lane_test.sh, DEVELOPMENT.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @a3f106f1 2026-10-12T12:12:37+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung:
- R-0266: In `lane_db` (:81) wird die Passwort-Gruppe von `([^@]*)` zu `([^@/]*)`.
  - Heute läuft sie über `/` hinaus. `postgresql://localhost:5432/adminhelper_test?application_name=a:b@c` wird als
    Benutzer `localhost` mit einem „Passwort“ aus Port, Pfad und Query zerlegt, und `createdb` bekommt
    `postgresql://localhost@c`.
  - Nach der Änderung bleibt die URL ganz.
  - Im Userinfo-Teil steht ein `/` laut URL-Syntax nie unkodiert, ein echtes Passwort fällt also nicht heraus.
- R-0265: Steht nach dem Herauslösen `[?&]password=` in der URL, endet `lane_db` mit Exit 3, wie bei R-0255.
  - Meldung: „AH_TEST_DB carries its password in the query; write it as user:password@ before the host“, ohne URL.
  - Ohne das ginge die URL samt Passwort als `--maintenance-db=…` in ein Argument von `createdb`/`dropdb`, und jeder
    lokale Benutzer kann Argumente lesen (der Kommentar in `lane_db`, :77–80).
- Neue Fälle in lane_test, beim Abschnitt zu R-0255:
  - `…/adminhelper_test?password=secret` und `…?sslmode=disable&password=secret`: Exit 1, kein createdb, keine Lane,
    die neue Meldung, kein `secret` in der Ausgabe;
  - `postgresql+psycopg://localhost:5432/adminhelper_test?application_name=a:b@c`: createdb bekommt genau diese URL
    (libpq-Form) und `PGPASSWORD` nicht gesetzt;
  - `postgresql+psycopg://ah:secret@localhost:5432/adminhelper_test?application_name=a:b@c`: createdb bekommt
    `pw=secret` und `postgresql://ah@localhost:5432/adminhelper_test?application_name=a:b@c`;
  - die Lanes der beiden letzten Fälle räumt `done` wieder ab.
- DEVELOPMENT.md (:204–210, „Eine Lane hat ihre eigene Test-DB“) ergänzt den Satz zum Passwort: Ein Passwort in der
  Query lehnt `lane.sh` ebenso ab.
Rot vorher:
- Auf main legt `lane new` für `?password=secret` eine Lane an, und createdb bekommt die URL mit dem Passwort im
  Argument.
- Für `localhost:5432/…?application_name=a:b@c` bekommt createdb `postgresql://localhost@c`.
Beweis: origin/main@40d3eb0a in bash, mit dem Muster aus `lane_db` (:81):
- `[[ "postgresql://localhost:5432/adminhelper_test?application_name=a:b@c" =~ ^(postgresql://[^:@/]+):([^@]*)@(.*)$ ]]`
  trifft. Daraus wird die URL `postgresql://localhost@c`, das „Passwort“ hat 42 Zeichen.
- Mit `([^@/]*)` trifft es nicht.
- `postgresql://ah@localhost:5432/adminhelper_test?password=secret` trifft weder das Muster noch die R-0255-Prüfung
  (:89). Die URL geht unverändert weiter.
Dedup-Key: ref:scripts:lane.sh:query-password
HEAD: 40d3eb0a
Semantik: DEVELOPMENT.md:208–210 „Steht das Passwort als `Benutzer:Passwort@` in der URL, reist es in `PGPASSWORD`,
nicht in einem Argument von `createdb`/`dropdb`; kann `lane.sh` es dort nicht herauslösen, legt es keine Lane an.“
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md (ein Satz)

### T2 — lane_done: Exit 3 heißt „nicht gelöscht, siehe oben“, nicht „dropdb failed“ (R-0269)  [x]
Komponente: scripts · Dateien: scripts/dev/lane.sh, scripts/tests/lane_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @a5eeb9cf 2026-10-12T12:26:58+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung:
- In `lane_done` (:334–335) fängt `rc=0; lane_db drop "$slug" || rc=$?` den Rückgabewert, wie in `lane_new` (:171).
  lane.sh läuft unter `set -e`, darum nicht `lane_db drop; rc=$?`.
  - Bei 3 lief dropdb nicht, denn lane_db lehnte die URL vorher ab, und die Zeile davor sagt warum. Die Meldung heißt
    dann „database <db> is not dropped — the line above says why; the mark stays“.
  - Bei jedem anderen Wert bleibt „dropdb failed — database <db> is left behind, and so is the mark“.
  - Beides mit Exit 1, die Marke bleibt.
- Die Rücknahmen in `lane_new` (:189, :201) bleiben. Sie laufen nur nach einem gelungenen createdb mit derselben URL,
  dort gibt es keine 3.
- Fall in lane_test:
  - Eine Lane wird normal angelegt.
  - Danach steht in `.devenv.sh` eine Form, die lane_db mit 3 ablehnt, etwa `?password=secret` aus T1.
  - Dann gibt `lane done`: Exit 1, kein dropdb-Aufruf, „is not dropped“ und nicht „dropdb failed“, die Marke mit der
    `db=`-Zeile bleibt, kein `secret` in der Ausgabe.
  - Danach wird `.devenv.sh` zurückgesetzt und `done` noch einmal gefahren, das räumt ab.
  - Bei einem dropdb, das selbst scheitert, bleibt die alte Meldung (Fake-dropdb mit Exit 1).
Rot vorher: Auf main meldet `done` in diesem Fall „dropdb failed“, obwohl kein dropdb lief.
Beweis: origin/main@40d3eb0a, lane.sh:334–335: `lane_db drop "$slug" || { echo "  dropdb failed — database $db is
left behind, and so is the mark"; exit 1; }`. Ein Rückgabewert von 3 aus lane_db (:91) landet dort.
Dedup-Key: ref:scripts:lane.sh:done-message
HEAD: 40d3eb0a
Semantik: lane.sh, Kopf (:23–25): „A mark that outlives `done` (no .devenv.sh, dropdb failed) makes `new <slug>` refuse
as "never closed": run `done <slug>` again, or drop the database by hand and remove the mark.“ Die Meldung soll den
Grund nennen, den der Kopf beschreibt. Unter docs/ gibt es keine Stelle dazu, gesucht wurde nach lane.sh done und
dropdb.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern; die Meldung ist der Text)
Abhängt von: T1

### T3 — Nachbesserung aus dem Review am Ende: lane_db liest die URL wie SQLAlchemy, kodierte Query-Schlüssel abgelehnt (R-0266, R-0265)  [x]
Komponente: scripts · Dateien: scripts/dev/lane.sh, scripts/tests/lane_test.sh, DEVELOPMENT.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @d04a7fef 2026-10-12T12:50:19+02:00
Review: Nachbesserung, Opus-Review über den Diff der Nachbesserungen folgt
Änderung: Angelegt 2026-10-12 aus dem Review am Ende (Opus, `request_changes`: ein Blocker in T1, zwei nits). Den Weg
(B) hat die Aufsicht entschieden.
- **R-0266 ist ein Falsch-Positiv.** `AH_TEST_DB` ist eine SQLAlchemy-URL. SQLAlchemy liest das Passwort mit `[^@]*`,
  über `/` hinweg (`sqlalchemy/engine/url.py`, Muster für das Passwort; geprüft mit `make_url` in 2.0.51 aus dem
  Server-venv, der Reviewer sah es in 2.1.1).
  - `ah:pa/ss@localhost…` ergibt Passwort `pa/ss` und Host `localhost`.
  - `localhost:5432/…?application_name=a:b@c` ergibt Benutzer `localhost` und Host `c`; genau so las es das alte
    `lane_db`. Eine solche URL kann im Haupt-Checkout keine funktionierende Test-DB sein.
  - Die Änderung von T1 an der Gruppe (`([^@/]*)`) war deshalb eine Regression. Ein Passwort mit unkodiertem `/` (etwa
    base64) löste `lane_db` nicht mehr heraus, und die URL ging samt Passwort in das Argument von createdb.
  - Neu: Die Gruppe steht wieder auf `([^@]*)`, der Kommentar sagt, dass sie wie SQLAlchemy liest.
  - T1 bleibt `[x]`, denn es trägt auch R-0265. Den Teil zu R-0266 nimmt diese Task zurück.
- Der Fall `upsilon` aus T1 (die URL bleibt ganz) geht. An seine Stelle kommt der Schutzfall `ah:pa/ss@…`: createdb
  bekommt `pw=pa/ss` und die URL ohne Passwort, und kein Argument enthält das Passwort. Der Fall `phi` bleibt.
- R-0265, nit aus demselben Review: libpq dekodiert auch Schlüssel der Query, so käme `?pass%77ord=secret` an
  `[?&]password=` vorbei.
  - Neu: Ein Schlüssel der Query mit `%` lässt `lane_db` geschlossen fehlschlagen (Exit 3, Meldung ohne URL).
  - Fall in lane_test; ein Satz in DEVELOPMENT.md (:208–210).
- nit: Der Fall `psi` (T2) prüft auch die Zeile davor („carries its password in the query“).
Test-Löschung: scripts/tests/lane_test.sh::upsilon: createdb gets the URL whole, a password only from user:password@ — der Fall prüfte die Änderung aus T1 an der Gruppe, die als Regression zurückgenommen wird (R-0266 Falsch-Positiv, Entscheidung der Aufsicht 2026-10-12); der Schutzfall ah:pa/ss@ tritt an seine Stelle
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md (ein Satz)
Abhängt von: T2
