<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness-Paket harness-lane-2: weitere Geheimnisse in der Query, Passwort wie SQLAlchemy dekodiert, doc-smoke.py als Harness-Pfad (R-0310, R-0313, R-0305) — Task-Ledger
Status: bereit · Branch: harness/harness-lane-2 · Commit-Granularität: pro Task · Review: am Ende (Opus) · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-12 (kleines Fund-Paket aus R-0310, R-0313, R-0305, Triage Kevin 2026-10-12; Fragen: 2 ein dekodiertes Passwort ohne UTF-8 wird mit Exit 3 abgelehnt, 3 doc-smoke-allow.txt kommt mit in harness-paths.txt; Bau nach lane-state-guard; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0310, R-0313, R-0305 (Kurz-Ledger ohne Spec)
Heavy: none — lane.sh (lane_db) mit Fake-createdb/dropdb in lane_test, harness-paths.txt mit hooks_test; nur Platzhalter, kein echter createdb, kein Stack-, Gateway-, PKI- oder Install-Pfad.
Hängt ab von: harness/lane-state-guard — kein gemeinsamer Code, aber beide sind Harness-Pakete auf derselben
scripts-Suite, und Kevin reiht lane-state-guard davor. T1 und T2 ändern lane_test.sh, das harness/lane-reap-guard
(#133) auch ändert: erst nach dessen Merge bauen und origin/main vorher hineinmergen.
DoD je Task: CLAUDE.md (Tests grün, shellcheck/ruff sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-12 von Worker A für die Aufsicht (adminhelper-ac). Kevin hat die drei Zeilen am 2026-10-12
angenommen. Zeilenangaben origin/main@bf9d0a5c; beim Bau an Symbolen orientieren.

Vorab geprüft:
- `AH_TEST_DB` trägt ein Passwort. Für Plan und Bau gilt:
  - Proben und Tests nur mit Platzhaltern (`secret`, `pa/ss`, `50%zz`).
  - Nie die echte `.devenv.sh` lesen oder eine DB-URL ausgeben.
  - Jeder neue Fall prüft, dass der Platzhalter weder in der Ausgabe noch in einem Argument der Fake-Programme
    steht.
- libpq-Doku (PostgreSQL 18, „Parameter Key Words“), am 2026-10-12 per WebFetch gelesen:
  - Einen eigenen geheimen Wert tragen `password`, `sslpassword` („the password for the secret key specified in
    sslkey“) und `oauth_client_secret` („The client password, if any, to use when contacting the OAuth authorization
    server“).
  - `scram_client_key`/`scram_server_key` sind laut Doku „base64-encoded SCRAM client/server key“, für Middleware.
    Dass der ClientKey zur Anmeldung reicht, folgt aus RFC 5802 (ClientProof = ClientKey XOR ClientSignature). Das
    ist abgeleitet, nicht wörtlich in der libpq-Doku.
  - `passfile`, `sslkey` und `service` nennen nur Pfade oder Namen.
- SQLAlchemy 2.0.51 (apps/server/.venv, `sqlalchemy/engine/url.py` `_parse_url`) dekodiert das Passwort mit
  `urllib.parse.unquote`:
  - Nur `%` mit zwei Hex-Ziffern wird zum Byte, alles andere bleibt stehen.
  - Danach wird als UTF-8 mit `errors="replace"` gelesen.
- Gemessen mit Platzhaltern, bash `printf '%b' "${pass//%/\\x}"` (lane.sh :87) gegen `unquote`:

  | Eingabe | bash | unquote |
  |---|---|---|
  | `50%zz` | `50\xzz` (Fehler „Fehlende hexadezimale Ziffer“) | `50%zz` |
  | `a%4zb` | `a\x04zb` | `a%4zb` |
  | `a%%41b` | `a\xAb` | `a%Ab` |
  | `x%` | `x\x` | `x%` |
  | `%ff` | Byte 0xff | U+FFFD |
  | `pa%2Fss`, `%C3%A4` | wie `unquote` | |

  - Dazu schneidet `$(…)` ein dekodiertes `%0A` am Ende ab.

### T1 — lane_db lehnt jedes Geheimnis in der Query ab, nicht nur password= (R-0310)  [x]
Komponente: scripts · Dateien: scripts/dev/lane.sh, scripts/tests/lane_test.sh, DEVELOPMENT.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @fbed6364 2026-10-12T23:32:59+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung:
- `lane_db` (:99–103) lehnt heute nur `[?&]password=` ab. Steht `sslpassword=`, `oauth_client_secret=`,
  `scram_client_key=` oder `scram_server_key=` in der Query, geht die URL samt Wert in
  `createdb --maintenance-db=…`, also in ein Argument, das jeder lokale Nutzer lesen kann.
- Neu: Eine zweite Prüfung neben der bestehenden lehnt diese vier Schlüssel ab.
  - Exit 3, keine Lane. Die Meldung nennt den Schlüssel, nie den Wert, etwa „AH_TEST_DB carries a secret in its query
    (sslpassword=); lane.sh does not pass it on“.
  - Verglichen wird ohne Rücksicht auf die Schreibweise (`SSLPassword=`). libpq lehnt einen falsch geschriebenen
    Schlüssel zwar ab, ob seine Meldung dann den Wert zitiert, ist aber nicht verifiziert. Also fail closed.
  - Die Prüfung und die Meldung für `password=` bleiben, wie sie sind (Fälle tau/chi :152–162).
- Fälle in lane_test, je Schlüssel einer, Platzhalter `secret`:
  - `new` endet ohne createdb und ohne Lane.
  - Die Meldung nennt den Schlüssel; `secret` steht nicht in `out.log` und nicht im PG-Log.
  - Ein Fall in anderer Schreibweise.
  - Ein Gegenfall `sslmode=disable` allein läuft durch.
Rot vorher: Auf main legt `new` mit `?sslpassword=secret` die Lane an, und im PG-Log steht `secret` im Argument
`--maintenance-db=`.
Beweis:
- origin/main@bf9d0a5c, lane.sh :99 `local query_pw='[?&]password='`.
- Fund: Opus-Review lane-paket, harness/lane-paket@efdda8eb.
Dedup-Key: ref:scripts:lane.sh:sslpassword-query
HEAD: bf9d0a5c
Semantik: DEVELOPMENT.md :204ff. („Eine Lane hat ihre eigene Test-DB“): „Steht das Passwort als
`Benutzer:Passwort@` in der URL, reist es in `PGPASSWORD`, nicht in einem Argument von `createdb`/`dropdb` … Ein
Passwort in der Query (`?password=`) lehnt `lane.sh` ebenso ab“. Unter docs/ gibt es keine Stelle zu `lane_db`.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md :210–211. Aus „Ein Passwort in der Query (`?password=`)“ wird „Ein Passwort oder ein anderes
Geheimnis in der Query (`password`, `sslpassword`, `oauth_client_secret`, `scram_client_key`, `scram_server_key`)“.

### T2 — lane_db dekodiert das Passwort wie SQLAlchemy (R-0313)  [x]
Komponente: scripts · Dateien: scripts/dev/lane.sh, scripts/tests/lane_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @5141fdc8 2026-10-12T23:51:21+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung:
- `lane_db` (:86–87) dekodiert mit `printf '%b'` jedes `%` als `\x`. SQLAlchemy nimmt nur `%` mit zwei Hex-Ziffern
  (`urllib.parse.unquote`).
  - Bei `50%zz`, `a%4zb`, `a%%41b` und `x%` reist so ein anderes `PGPASSWORD` als das, mit dem die Suiten sich
    anmelden. Kein Leck, aber `createdb` scheitert an der Anmeldung.
- Neu: eine kleine Funktion, die nur `%` mit zwei Hex-Ziffern dekodiert und alles andere stehen lässt.
  - Die Klasse ist ausgeschrieben (`[0123456789abcdefABCDEF]`, keine Bereiche, weil sie unter de_DE.UTF-8 mehr
    treffen).
  - Sie baut das Ergebnis mit `printf -v`, damit ein `%0A` am Ende bleibt.
- Ergibt das dekodierte Passwort kein gültiges UTF-8 (`%ff`), lehnt `lane_db` ab: Exit 3, ohne Wert in der Meldung.
  SQLAlchemy würde dort U+FFFD einsetzen, und dieses Passwort wäre ein anderes (Frage 2 am Gate).
- Fälle in lane_test:
  - Für jeden Platzhalter der Tabelle oben, außer `%ff`: Das `pw=` im PG-Log ist gleich dem, was
    `python3 -c 'import urllib.parse,sys; print(urllib.parse.unquote(sys.argv[1]))'` aus derselben Eingabe macht.
    Das Orakel ist der Verbraucher selbst.
  - `%ff`: Exit 3, keine Lane, kein Wert in der Ausgabe.
  - Der bestehende Fall `p%40ss%25w` (:508) bleibt unverändert grün.
Rot vorher: Auf main reist für `50%zz` `50\xzz` statt `50%zz` in `PGPASSWORD`.
Beweis:
- origin/main@bf9d0a5c, lane.sh :86–87.
- Die Messung oben.
- Fund: Bau lane-paket, harness/lane-paket@0801e35d.
Dedup-Key: ref:scripts:lane.sh:raw-percent-password
HEAD: bf9d0a5c
Semantik: lane.sh :78–81 („a password the suites take out of the URL is one lane_db takes out too (R-0266)“) und
DEVELOPMENT.md :204ff. Unter docs/ gibt es keine Stelle zu `lane_db`.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern; das Verhalten gleicht sich nur dem dokumentierten an)

### T3 — doc-smoke.py ist ein Harness-Pfad (R-0305)  [x]
Komponente: scripts · Dateien: scripts/dev/harness-paths.txt, scripts/tests/hooks_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @64cf8042 2026-10-13T00:07:27+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung:
- Seit R-0304 darf die Bau-Session genau `python3 scripts/dev/doc-smoke.py --paths --env --strict` starten
  (runner-settings.json :83).
  - Wer das Skript ändert, führt beliebigen Code unter dieser Regel aus.
  - Das ist derselbe Grund, aus dem die vm-Wrapper in der Liste stehen (harness-paths.txt :49–50: „the runner is
    allowed to START them: editing one is arbitrary code execution“).
  - `deny Edit(./scripts/dev/**)` hält heute. Es fehlen die zweite Schicht, der Wächter, und das Risiko-Routing
    (`review.sh risk` → xhigh).
- Neu: `scripts/dev/doc-smoke.py` steht in harness-paths.txt unter „The gates“, mit einer Kommentarzeile wie bei den
  Wrappern.
  - Wächter und Risiko-Routing lesen die Liste und ziehen von selbst nach.
- hooks_test:
  - `scripts/dev/doc-smoke.py` kommt in die Liste der Pflicht-Einträge (:189–194).
  - Ein Fall `guard auto Edit` auf `$TREE/scripts/dev/doc-smoke.py` wird verweigert, wie bei roadmap.py (:273–275).
- `scripts/dev/doc-smoke-allow.txt` kommt nur auf Entscheidung am Gate dazu (Frage 3).
Rot vorher: Auf main lässt der Wächter im autonomen Lauf ein Edit an `scripts/dev/doc-smoke.py` durch, und der
Pflicht-Eintrag fehlt.
Beweis:
- origin/main@bf9d0a5c, harness-paths.txt nennt `doc-smoke.py` nicht (`grep -c doc-smoke` = 0).
- runner-settings.json :83.
- Fund: Bau loop-harness, harness/loop-harness@25f18d59.
Dedup-Key: ref:scripts:harness-paths.txt:doc-smoke
HEAD: bf9d0a5c
Semantik: harness-paths.txt :9–10 („Add a path here when changing it would change the RULES a run obeys“) und
:49–50. Unter docs/ gibt es keine Stelle zu harness-paths.txt.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern)

### T4 — lane_db lehnt eine Test-DB-URL ab, die kein UTF-8 ist  [x]
Komponente: scripts · Dateien: scripts/dev/lane.sh, scripts/tests/lane_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @5d1fa6af 2026-10-13T00:48:46+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung: Angelegt 2026-10-13 auf Entscheidung der Aufsicht (adminhelper-ac), aus dem Review am Ende (Opus, `approve`).
- `lane_db` liest die URL mit Mustern, die UTF-8 erwarten. Ganz vorne lehnt es jetzt eine `AH_TEST_DB` ab, die kein
  UTF-8 ist: Exit 3, ohne Wert in der Meldung. Die Prüfung ist dieselbe wie in T2 (`iconv -f UTF-8 -t UTF-16LE`).
- Fälle in lane_test, mit Platzhaltern:
  - ein Byte, das kein UTF-8 ist, im Passwort und eines im Nutzer. Beide Male: keine Lane, kein createdb, kein
    Platzhalter in Ausgabe oder PG-Log.
- nits aus dem Review:
  - Die Fälle `%ff`/`%00` aus T2 bekommen einen eindeutigen Platzhalter und prüfen auch den dekodierten Wert.
  - Ein Fall `%0A` am Ende prüft, dass der Zeilenumbruch in `PGPASSWORD` bleibt.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern)
Abhängt von: T2
