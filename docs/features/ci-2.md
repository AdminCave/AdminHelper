<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# CI: Server-pytest in Shards

Zug `ci-2` (Roadmap R-0950). Stand des Codes: `origin/main@0c474527`.

## Problem / Motivation

Die drei Server-pytest-Jobs in `.github/workflows/ci.yml` (`Server (pytest, py3.12)`, `Server (pytest, py3.13)`,
`Server (pytest, image lock)`) brauchen je 13–14 min (Lauf 41092318397, 2026-10-30); ihr Deckel liegt bei 25 min
(R-0947). Sie sind die langsamsten PR-Jobs und bestimmen die Dauer jedes PR-Zyklus.

Messung (lokal, `verify.sh server --strict -- --durations=60`, 2026-10-30): 2564 Tests in 1452 s; die 60
langsamsten zusammen 446 s (Webhook-Ratelimit 34 s, Gateway-/frps-Container 6–19 s je Test). Gut zwei Drittel der
Zeit verteilen sich also auf rund 2500 Tests mit je etwa 0,4 s (Fixtures, App, DB). Einzelne langsame Tests zu
beschleunigen spart höchstens ein Drittel; nur Parallelität halbiert die Laufzeit.

## Ziel & Nicht-Ziele

- Ziel: Jeder der drei Server-Jobs läuft in zwei Shards parallel, je Shard etwa die halbe Suite; die PR-Wandzeit
  der Server-Tests sinkt von ~14 auf ~8 min.
- Ziel: Die Pflicht-Checks des Rulesets (`Server (pytest, py3.12)`, `Server (pytest, py3.13)`) behalten ihre
  Namen, als Sammeljob über die Shards; das Ruleset bleibt unverändert.
- Ziel: Die Skip-Prüfung der 3.13-Leg gilt weiter für jeden Test (je Shard über sein JUnit-XML).
- Nicht-Ziel: pytest-xdist (siehe Trade-offs), einzelne langsame Tests beschleunigen (eigene Zeilen, falls nötig),
  lokale Läufe (`run.sh`, `verify.sh`) ändern.

## Betroffene Komponenten & Dateien

- `apps/server/tests/conftest.py`: neue Option `--shard K/N` und ein Hook `pytest_collection_modifyitems`, der die
  Tests der anderen Shards abwählt (`pytest_deselected`).
- `apps/server/tests/test_shard.py` (neu): Aufteilung vollständig und disjunkt, deterministisch, ganze Dateien
  zusammen, ungültige Werte abgewiesen.
- `.github/workflows/ci.yml`: Shard-Matrix für `server` und `python-lock-server`, Sammeljobs mit den alten Namen.
- `apps/server/tests/test_release_images.py` oder ein neuer Test: Shard-Matrix und `--shard`-Aufruf in `ci.yml`
  passen zueinander (jede Nummer 1..N genau einmal, dasselbe N).
- `docs/developer/cicd.html` + `docs/en/developer/cicd.html`: Server-Jobs in Shards, Sammeljob, Skip-Prüfung je
  Shard.

## Datenmodell / API / Migrationen

Keine. Keine neue Abhängigkeit.

## Aufteilung

Einheit ist die Testdatei (Fixtures mit `scope="module"` und Container-Tests einer Datei bleiben zusammen).
Dateien mit den meisten Tests zuerst (bei Gleichstand nach Pfad), jede geht an den Shard mit den bisher
wenigsten Tests (bei Gleichstand der kleinste Index). Geteilt wird nach `-m`/`-k`. Ohne `--shard` läuft alles wie heute.

## Externe Integrationen

GitHub Actions: `needs` auf einen Matrix-Job liefert ein Gesamtergebnis über alle Legs
(https://docs.github.com/en/actions/writing-workflows/choosing-what-your-workflow-does/accessing-contextual-information-about-workflow-runs#needs-context).
Ein Sammeljob mit `if: always()` prüft `needs.<job>.result == 'success'`.

## Trade-offs & Alternativen

- **Shards (Empfehlung):** keine neue Abhängigkeit, jede Leg hat weiter ihre eigene DB und ihren eigenen Docker,
  kein neues Nebenläufigkeitsrisiko in den Tests. Kosten: drei Jobs mehr plus zwei Sammeljobs; das Repo ist
  öffentlich, Actions-Minuten auf Standard-Runnern kosten nichts. Install-Schritt (~1–2 min) läuft je Shard.
  Coverage wird je Shard berichtet (report-only, kein Gate).
- **pytest-xdist mit getrennten DBs:** ein Job, `-n 4`; braucht aber eine DB je Worker in der Session-Fixture,
  und die Container-Tests (Gateway, frps), der Bootstrap-Lock und `DATA_DIR` sind nicht für parallele Prozesse
  gebaut. Mehr Risiko, neue Abhängigkeit.
- **Langsame Tests zuerst:** spart höchstens ~7 min Summe über alle Legs, verteilt.

## Risiken & Rollback

- Ein Fehler in der Aufteilung ließe Tests aus: der Test `test_shard.py` prüft Vollständigkeit; die Sammeljobs
  sind nur grün, wenn jeder Shard grün ist.
- Gesamtergebnis eines Matrix-`needs`: der Sammeljob von 3.12 wird auch rot, wenn ein 3.13-Shard rot ist. Beide
  sind Pflicht-Checks, das Merge-Ergebnis ist dasselbe; der Name zeigt nur nicht genau die Leg.
- Rollback: Revert.
- Der PR ändert `.github/workflows/` und wird von Kevin gemergt.

## Doku-Impact

`docs/developer/cicd.html` + EN: Server-Jobs in zwei Shards mit Sammeljob unter dem alten Namen, Skip-Prüfung je
Shard. CHANGELOG: keiner (nur CI).

## Offene Fragen

Keine. Anzahl der Shards: 2 (Entscheidung der Session; mehr erst, wenn die Messung in CI es rechtfertigt).
