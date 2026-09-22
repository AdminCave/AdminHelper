<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# oasdiff: eine engere Eingabemenge ist kein Bruch — Task-Ledger
Status: geplant · Branch: harness/oasdiff-narrowing · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Spec: dieses Ledger (Harness-Fix an bestehendem Gate, kein eigenes Spec-Dokument)
Fast-Suite: lokal · Warm-Profil: desktop
Heavy: nein — der Diff berührt `scripts/dev/`, `scripts/tests/` und zwei Doku-Seiten.
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, Doku im selben Commit).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

## Warum

Das Gate `OpenAPI breaking changes (oasdiff)` stuft ein **neu gesetztes** `maximum` oder `minimum`
auf einem Request-Parameter oder Body-Feld als `ERR` ein — eine Verengung der Eingabemenge gilt
dort als Bruch. Das Gate ist **Pflicht-Check im Ruleset 23772038, und das Ruleset hat null
Bypass-Akteure**: ein roter Lauf bedeutet nicht „rot mit Begründung", sondern der PR ist nicht
mergebar, auch nicht für Kevin. Damit blockiert dieses Gate die Randvalidierung
(`tasks/input-boundary-validation.md`) vollständig, und zwar durch jede ihrer Tasks.

Sachlich ist die Einstufung hier falsch herum: die Werte, die künftig abgelehnt werden, liefern
heute **HTTP 500**. Es gibt also keinen Client, der davon lebt — ein Client, der gültige Werte
schickt, merkt nichts, und einer, der ungültige schickt, bekommt statt eines Serverfehlers eine
Validierungsmeldung. Das ist eine Verbesserung, die das Werkzeug nicht von einem echten Bruch
unterscheiden kann.

Alles gegen die in CI gepinnte Version **v1.32.0** gelesen, nicht gegen `main` und nicht geraten:
- Einstufung `ERR`: `checker/rules.go` Z. 272/288 (Parameter), Z. 381/408–411 (Body).
- Die Id-Strings: `checker/check_request_parameters_{max,min}_set.go` und
  `checker/check_request_property_{max,min}_set.go`.
- `--severity-levels` existiert: `internal/flags.go:153`.
- Dateiformat: `checker/level.go:42` — `strings.Fields(line)`, **genau zwei Felder je Zeile**,
  unbekannte Id ist ein harter Fehler, Stufen sind `ERR|WARN|INFO|NONE` (auch klein).
  **Die Datei erlaubt keine Kommentare und keine Leerzeilen** — jede Zeile, die nicht aus zwei
  Feldern besteht, bricht den Lauf ab. Die Begründung muss daneben stehen, nicht darin.

## Was das Gate weiter fängt

Herabgesetzt werden **nur** die zwölf Regeln, die ein *neues* `minimum`/`maximum` auf einer
Eingabe meinen. Alles andere bleibt `ERR`: entfernte Endpunkte, entfernte oder umbenannte
Antwortfelder, neue Pflichtfelder im Request, verschärfte Typen, geänderte Statuscodes. Ein Gate,
das nichts mehr fängt, wäre keins — deshalb keine pauschale Absenkung und kein `--fail-on WARN`.

### T1 — Die zwölf Narrowing-Regeln als WARN, mit Beleg daneben  [ ]
Komponente: scripts · Dateien: scripts/dev/oasdiff-severity.levels (neu), scripts/dev/openapi-breaking.sh, scripts/tests/openapi_breaking_test.sh
Änderung: Neue Datei mit genau zwölf Zeilen `<rule-id> warn` — `request-parameter-max-set`, `request-parameter-min-set`, `request-parameter-exclusive-max-set`, `request-parameter-exclusive-min-set`, `request-body-max-set`, `request-body-min-set`, `request-body-exclusive-max-set`, `request-body-exclusive-min-set`, `request-property-max-set`, `request-property-min-set`, `request-property-exclusive-max-set`, `request-property-exclusive-min-set`. Kein Kommentar in der Datei (der Parser verbietet es); die Begründung steht im Kopf von `openapi-breaking.sh` und in der Doku. Das Skript gibt `--severity-levels <datei>` mit, **wenn die Datei existiert** — fehlt sie, läuft das Gate unverändert streng weiter, statt still zu lockern. Test: die Argumentprüfung des bestehenden Falls erwartet das Flag zusätzlich; dazu ein eigener Fall, der die Datei selbst prüft (genau zwei Felder je Zeile, keine Leerzeile, Stufe immer `warn`, keine doppelte Id, genau die zwölf erwarteten Ids).
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: keine (T2)

### T2 — Doku: was das Gate erlaubt und warum  [ ]
Komponente: scripts · Dateien: docs/developer/cicd.html, docs/en/developer/cicd.html
Änderung: Im Abschnitt zum oasdiff-Gate zwei bis drei Sätze DE und EN: dass eine neu gesetzte Ober- oder Untergrenze auf einer Eingabe als `WARN` läuft, warum (die betroffenen Werte liefern heute 500, kein Client lebt davon), dass die Absenkung auf zwölf namentlich genannte Regeln begrenzt ist und alles andere `ERR` bleibt, und wo die Datei liegt. Kein `CHANGELOG`-Eintrag: das ist Gate-Verhalten im Bau, nichts am Produkt nach außen.
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: docs/developer/cicd.html + docs/en/developer/cicd.html (DE+EN im selben Commit)
Abhängt von: T1
