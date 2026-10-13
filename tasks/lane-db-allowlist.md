<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# lane.sh: lane_db nimmt nur postgresql://-URLs und liest sie unter C — Task-Ledger
Status: erledigt · Branch: harness/lane-db-allowlist · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-13 (kleines Fund-Paket, Triage Kevin 2026-10-13; T2 ohne Skip: fehlt die Locale-Quelle im CI, ist der Fall rot und wird nachgezogen; Delegation Kevin 2026-10-05)
Spec: Kevin 2026-10-13 (Kurz-Ledger ohne Spec)
Heavy: none — `lane_db` in `scripts/dev/lane.sh` und sein hermetischer Test; kein Stack-, Gateway-, PKI- oder Install-Pfad.
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, Doku im selben Commit).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-13 von Worker B im Auftrag der Aufsicht (adminhelper-ac), angenommen von Kevin am 2026-10-13.
Zeilenangaben origin/main@7860cfdd. `scripts/dev/lane.sh` und `scripts/tests/lane_test.sh` sind Harness-Pfade; den PR
merged Kevin oder die Aufsicht auf sein Wort. Alle Werte in Tests und Proben sind Platzhalter.

`lane_db` (`lane.sh:74-147`) legt die Test-Datenbank einer Lane mit `createdb`/`dropdb` auf dem Server an, den
`AH_TEST_DB` des Haupt-Checkouts nennt. `lane_db_url` (`:66-72`) macht aus `postgresql+<treiber>://` ein
`postgresql://`. Danach prüft `lane_db` einige Formen (ohne UTF-8, Passwort nicht herauszulösen, Geheimnisse in der
Query), das Schema aber nicht.

### T1 — lane_db: nur eine URL, die mit `postgresql://` beginnt, erreicht createdb/dropdb  [x]
Komponente: scripts · Dateien: scripts/dev/lane.sh, scripts/tests/lane_test.sh, DEVELOPMENT.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @13a1a689 2026-10-13T05:53:31+02:00
Review: Review am Ende (Kurz-Ledger, Opus)
Änderung:
- `lane_db`: Unmittelbar vor `case "$1" in` (`:142`), nach allen bisherigen Prüfungen, nimmt die Funktion nur noch eine
  URL an, die mit `postgresql://` beginnt. Jede andere Form endet mit einer Meldung ohne Wert und `return 3`, wie die
  bisherigen Ablehnungen. Die bisherigen Prüfungen und ihre Meldungen bleiben, wie sie sind; die neue fängt nur, was
  heute an ihnen vorbeigeht.
- `lane_test.sh`: neue Fälle nach dem Muster von `:137-151` (Platzhalter, die Attrappe von `createdb` zeichnet auf).
  Zwei Formen ohne `postgresql://` ergeben je: kein `createdb`, keine Lane, kein Wert in der Ausgabe.
  - die Keyword-Form von libpq (`host=… user=… password=… dbname=…`);
  - `postgresql+psycopg:` ohne `//`.
- Die bestehenden Fälle mit `postgresql+psycopg://` bleiben grün.
- `DEVELOPMENT.md`, Absatz „Eine Lane hat ihre eigene Test-DB“ (`:204-216`), nennt die Regeln von `lane.sh` für
  `AH_TEST_DB`. Ein Satz dazu: Eine andere Form als eine URL `postgresql://` oder `postgresql+<treiber>://`, etwa die
  Keyword-Form von libpq, lehnt `lane.sh` ab.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md (Absatz zur Test-DB einer Lane)
Beweis: origin/main@7860cfdd. Die Probe (nicht committet, Platzhalter, dreimal identisch) zieht `lane_db_url` und
`lane_db` aus `lane.sh` und stellt eine `createdb`-Attrappe davor. Zwei Formen ohne `postgresql://` erreichen den Aufruf
von `createdb`, je mit rc 0:
- `host=db.invalid user=ah password=… dbname=adminhelper_test`;
- `postgresql+psycopg:ah:…@db.invalid/adminhelper_test`.
Orakel: mutation-sample — die neue Prüfung entfernt: die neuen Fälle in `lane_test.sh` rot.
HEAD: 7860cfdd
Semantik: `lane.sh:61-63`: „That URL is SQLAlchemy's (postgresql+psycopg://…); libpq wants plain postgresql://, and
--maintenance-db takes a whole connection string.“ Was nicht diese Form hat, ist keine, die `lane_db` kennt.

### T2 — lane_db liest die URL byteweise, unabhängig von der Locale des Aufrufers  [x]
Komponente: scripts · Dateien: scripts/dev/lane.sh, scripts/tests/lane_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @68ad3c9d 2026-10-13T07:05:44+02:00
Review: Review am Ende (Kurz-Ledger, Opus): approve, Nit miterledigt
Abhängt von: T1
Änderung:
- `lane_db` setzt am Anfang `local LC_ALL=C`. Die Muster der Funktion lesen damit Bytes, auch unter einer
  Mehrbyte-Locale des Aufrufers. Die Prüfung auf UTF-8 (`iconv -f UTF-8`) nennt ihre Kodierung selbst und bleibt.
- `lane_test.sh`: ein Fall unter GBK. `localedef -i zh_CN -f GBK` baut die Locale in den Testordner, und `LOCPATH`
  muss schon beim Start des Prozesses stehen, denn glibc liest es aus der Umgebung des Prozesses.
  - URL: Platzhalter, ein Zeichen wie `中` direkt vor `@`.
  - Erwartet: `lane new` übergibt `createdb` dieselbe URL wie unter `LC_ALL=C`. Verglichen werden die aufgezeichneten
    Argumente und die Umgebung der Attrappe.
- Kann `localedef` die Locale nicht bauen, ist der Fall ein `bad` mit Grund, kein stilles Grün.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern)
Beweis: origin/main@7860cfdd. Die Probe (nicht committet, Platzhalter, dreimal identisch) nimmt dieselben Funktionen
und dieselbe Attrappe. Die URL `postgresql+psycopg://ah:…中@db.invalid/adminhelper_test` ergibt für `createdb` unter
`zh_CN.GBK` (per `localedef` in einen eigenen Ordner gebaut, `LOCPATH`) eine andere URL als unter `LC_ALL=C`.
Orakel: mutation-sample — `local LC_ALL=C` entfernt: der GBK-Fall rot.
HEAD: 7860cfdd
Semantik: `lane.sh:84-87`: „The password runs to the first @, across a /, the way SQLAlchemy reads AH_TEST_DB … a
password the suites take out of the URL is one lane_db takes out too“. SQLAlchemy liest Zeichen, nicht die Bytes einer
Locale. `lane_db` muss dieselbe Stelle finden, gleich unter welcher Locale `lane.sh` läuft.
