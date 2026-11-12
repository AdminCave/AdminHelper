# Harness: Sammellauf ohne Server-pytest auf der Box

Zug `arch-workflow-2` (Roadmap R-1338). Kevin hat das am 2026-11-11 diktiert, mit einer Bedingung: der Schritt fällt nur
weg, wenn die CI dieselben Tests fährt (Skip-Listen VM gegen CI vergleichen; sonst bleibt er). Verschoben aus
`arch-workflow-1` T6, weil das Auslassen eine Weiterleitung durch `scripts/vm/iter.sh` braucht.

## Problem

Teil `rest` des Sammellaufs (`heavy.sh all` → `iter.sh all --strict --part rest`) fährt die Server-Suite auf der Box:
1973 s im Lauf 2026-11-12-0130, p50 1817 s seit 11-05. Das ist rund ein Drittel von Teil `rest` (p50 111 min).
Dieselbe Suite läuft in der CI auf jedem PR und auf jedem `main`-Commit.

**Vergleich (die Bedingung der Zeile), frisch am 2026-11-12:**
- CI `main` @adf6652df (Lauf 43172301662), Server-pytest py3.14: Shard 1 hat 1708 passed, Shard 2 1707 passed, 0 skipped,
  zusammen 3415.
- Box, Sammellauf 2026-11-12-0130, JUnit `server-pytest.xml`: 3415 Tests, davon 54 skipped. 44 sind Image-Tests ohne
  Docker-Image, 5 die Migrationskette ohne Postgres-URL, 3 die App-Engine ohne `DATABASE_URL`, 2 Redis.
- Die Box fährt also keinen Test, den die CI auslässt. Umgekehrt fährt die CI 54 Tests, die die Box auslässt. Die
  Vorprobe vom 2026-11-11 (`arch-workflow-1` T6, CI 3319/0 skipped, Box 39 skipped) kam zum selben Ergebnis.
- Zwei Dinge hat nur die Box. Erstens den testcontainers-Modus der `apps/server/tests/conftest.py`: ohne `DATABASE_URL`
  startet die Fixture selbst ein Postgres. Zweitens Python 3.12 aus dem Box-Image. Das Server-Image läuft auf 3.14,
  die CI fährt 3.14 und 3.15.

**Versteckte Abhängigkeit.** Der Schritt `server-pytest` installiert `apps/server/requirements-dev.txt` in das
gemeinsame Venv (`scripts/tests/run.sh:737`). Zwei spätere Schritte leben davon, ohne es zu sagen:
- Schemathesis (`run.sh:752-793`) installiert nichts. Es prüft nur `import schemathesis` (das bringt schon Monitoring mit)
  und sammelt dann in `apps/server` Tests, die PyJWT, bcrypt, redis und python-multipart brauchen.
- `scripts/tests/sse_push_e2e.sh:36` bootstrapt das Venv nur, wenn `uvicorn` fehlt. Monitoring und ca-issuer bringen
  `uvicorn` mit, die Server-Pakete aber nicht.

Ohne `server-pytest` würden beide Schritte auf der Box rot. Dieselbe Lücke trifft heute schon einen Lauf mit `--step
schemathesis` auf einem frischen Venv. Das ist aus dem Code abgeleitet und auf keiner Box belegt.

## Ziel und Nicht-Ziele

- Ziel: Teil `rest` des Sammellaufs fährt `server-pytest` nicht mehr. Der Report sagt, dass der Schritt fehlt und warum.
- Ziel: jeder Schritt installiert selbst, was er braucht, und hängt nicht mehr an der Reihenfolge der Schritte.
- Nicht-Ziel: `.github/workflows/ci.yml` bleibt unverändert. Das ist Zug `arch-workflow-ci-1`, und Workflow-PRs merged
  Kevin.
- Nicht-Ziel: `run.sh quick` lokal, `run.sh … --part rest` ohne die neue Option, Teil `gui`, `capstone` und `multibox`
  bleiben, wie sie sind.
- Nicht-Ziel: es gibt keinen eigenen testcontainers-Smoke (siehe Risiken).

## Betroffene Komponenten und Dateien

Komponente `scripts` (Harness), keine Produktkomponente:
- `scripts/tests/run.sh`:
  - neue Option `--exclude <ids…>` (Env-Form `AH_EXCLUDE`)
  - Schemathesis installiert je Dienst dessen `requirements-dev.txt`
- `scripts/tests/sse_push_e2e.sh`: installiert die `requirements.txt` des Servers bei jedem Lauf, nicht nur bei
  fehlendem `uvicorn`. Das ist idempotent, ein erfüllter Stand kostet Sekunden.
- `scripts/tests/run_flags_test.sh`: die Tests zu beidem.
- `scripts/vm/iter.sh`, `scripts/tests/iter_flags_test.sh`: `--exclude` an die Box weiterreichen (Flag-Liste
  `iter.sh:181`).
- `scripts/tests/heavy.sh`, `scripts/tests/heavy_test.sh`: `part_job` (`heavy.sh:369-383`) hängt für Teil `rest`
  `--exclude server-pytest` an, und der Report bekommt eine Notiz dazu. Die Assertion `heavy_test.sh:1666` ändert sich
  mit.
- Doku: `DEVELOPMENT.md`, `docs/developer/cicd.html`, `docs/en/developer/cicd.html`, `.claude/rules/testing.md`,
  `.claude/skills/test/SKILL.md`.

Kein Datenmodell, keine API, keine Migration, kein Vertrag zwischen Server, Web, Desktop und Agent.

## Design `--exclude`

- Die Argumente sind Step-Ids wie in `AH_REQUIRED`, nicht Namen. `--exclude` frisst die folgenden Wörter wie `--only`.
- Ein ausgeschlossener Schritt gehört nicht zu diesem Lauf, wie ein Schritt außerhalb von `--part`. Er läuft nicht,
  erscheint nicht als SKIP und nicht im Artefakt. Unter `--strict` gilt er nicht als übersprungener Pflicht-Schritt.
- Geprüft wird in `run_step`, `run_py_step` und `skip`, und zwar vor dem Filter für Teil und Schritt. So ist eine Id
  unabhängig von `--part` und `--step` gültig.
- Eine unbekannte Id lehnt der Probelauf ab, den es schon für `--step` gibt (`run.sh:1003-1023`). Das passiert vor dem
  ersten Schritt, mit Exit 2. Wie bei `--step` erreicht der Probelauf einen Schritt hinter einer unerfüllten Vorbedingung
  nicht. `server-pytest` erreicht er immer, denn jeder Zweig im Block nennt die Id.
- Die Zusammenfassung druckt `excluded: <ids>`, und das Artefakt `last-<layer>.json` bekommt das Feld `exclude`. Ein
  verkleinerter Lauf darf nicht wie ein voller aussehen.
- `heavy.sh` setzt die Option, nicht `nightly.sh`, denn `heavy.sh all` ist der Sammellauf. Auch ein manueller `/test
  all` lässt den Schritt deshalb aus. Vor einem Release bleiben die `main`-CI und `run.sh quick --strict` lokal; dort
  läuft `server-pytest` gegen `AH_TEST_DB`.

## Trade-offs und Alternativen

- **A, empfohlen: `--exclude` in `run.sh`.** Allgemein, sichtbar in Zusammenfassung und Artefakt, mit Exit 2 bei einem
  Tippfehler. Der Preis ist eine Option mehr.
- **B: `AH_ONLY` ohne `server`.** Das nähme auch Schemathesis für `apps/server` und ruff für den Server aus dem Lauf.
  Verworfen.
- **C: `AH_REQUIRED` kürzen (`AH_REQUIRED_BOX`).** Der Schritt liefe weiter, nur sein SKIP wäre erlaubt. Spart nichts.
- **D: ein dritter `--part`-Wert.** Das vermischt die Aufteilung auf zwei Boxen mit dem Auslassen. Die Teile sind
  bewusst ein Prädikat und seine Verneinung.

## Risiken und Rollback

- **testcontainers-Modus.** Er läuft danach nirgends mehr regelmäßig, denn die CI und die Dev-Box setzen
  `DATABASE_URL` bzw. `AH_TEST_DB`. Ein Bruch dieses Fixture-Wegs, etwa durch ein Update von testcontainers, fiele erst
  jemandem auf, der ohne Datenbank-URL testet. Das Produkt betrifft das nicht, der Modus ist reine Test-Infrastruktur.
  R-0824 (10-22) war genau so ein Testfehler. Die Bedingung der Zeile („dieselben Tests“) ist erfüllt. Empfehlung:
  hinnehmen.
- **Python 3.12 entfällt.** Das ist keine ausgelieferte Laufzeit, denn das Server-Image läuft auf 3.14.
- **Weitere versteckte Abhängigkeiten.** Gesucht wurde über `scripts/tests`, `scripts/vm` und `scripts/dev` nach
  Verbrauchern von `apps/server`. `stack_pytest.sh` installiert seine Pakete selbst, sonst fand sich nichts. Den Beweis
  auf der Plattform liefert eine frisch geleaste Box der Lane vor dem Merge. Zuerst wird gegengeprüft, dass ihr Venv
  keine Server-Pakete trägt, dann laufen `iter.sh unit --strict --step schemathesis` und `iter.sh integration --strict
  --step sse_push`. Den Gesamtbeweis liefert der erste Sammellauf nach dem Merge (`Heavy: linux-full`). Ein roter
  Sammellauf sperrt `linux-full`-Merges, deshalb gibt es die gezielte Probe vorher.
- **Dev-Box.** Schemathesis ruft künftig dreimal `pip install` mit erfülltem Stand auf, das sind einige Sekunden je
  `run.sh quick`.
- **Rollback:** den PR revertieren. Teil `rest` fährt `server-pytest` dann wieder, und die Option in `run.sh` stört
  nicht.

## Doku-Impact

- `DEVELOPMENT.md`: die `run.sh`-Flags und der Wochenlauf-Punkt `all`.
- `docs/developer/cicd.html` DE+EN: die Flag-Tabelle des Test-Aggregators und der Abschnitt „Wochenlauf“.
- `.claude/rules/testing.md` und der `/test`-Skill: Flag-Liste und Teil `rest`.
- Kein CHANGELOG-Eintrag: das ist Harness, kein Nutzerverhalten.

## Offene Fragen

Keine, die den Bau aufhält. Das testcontainers-Restrisiko (siehe Risiken) geht als Hinweis mit Empfehlung „hinnehmen“
an Kevin.
