<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness Stufe 5 — Roadmap und Beweis

Roadmap-Zeile R-0008 · Quelle: privates Roadmap-Dokument §Stufe 5 · Stand 2026-09-25 · geschnitten in drei
Ledger: `tasks/harness-stufe-5a.md` (Roadmap als Skript), `tasks/harness-stufe-5b.md` (Planen und Beweis),
`tasks/harness-stufe-5c.md` (Test-Ausgaben und Pflicht-Tests gegen den Stack).

## Problem / Motivation

Der rote Faden `tasks/private/ROADMAP.md` wird heute von Hand gepflegt. Nur `heavy.sh` schreibt Zeilen, und das
ohne Sperre, ohne Dedup-Schlüssel und ohne Invariante. Die Folgen sind messbar (Bestandsaufnahme 2026-09-23):

- **R-0047 ist doppelt vergeben.** Die ID-Vergabe nimmt `max + 1` über den ganzen Text, von Hand wird dagegen
  frei gezählt.
- **Rund 30 Zeilen stehen im falschen Abschnitt.** Im Archiv liegen 16 `neu`-Zeilen, unter „In Arbeit“ und
  „Geplant“ abgeschlossene. Der WIP-Zähler im Kopf ist fünf Tage alt: `neu 7/20`, tatsächlich sind es 23.
- **Der Status-Hook zeigt nur vier Punkte** von „Als Nächstes“ und prüft keinen WIP-Deckel. Den Warn-Trigger 3
  aus CLAUDE.md gibt es damit nur auf dem Papier.

Beim Planen fehlt ein Modus für kleine Vorhaben. Heute wird jedes Kurz-Ledger wie eine volle Spec geschnitten.
`feature-plan` sagt außerdem noch „Plan auf `main` committen“ und widerspricht damit `AUTONOMOUS.md` und
`lane.sh` (R-0065).

Beim Beweisen: Die Evidenz einer Task ist eine Summary-Zeile. Für Funde aus Finder-Flotte, Hunt und Wochenlauf
(Stufen 7 und 9) gibt es noch kein Format, das festhält, was bewiesen ist, womit und wie es dedupliziert wird.

Beim Testen: Es gibt nirgends JUnit-XML. Wer einen roten Wochenlauf klassifiziert, liest Logs. Drei Tests, die
echtes Postgres oder Redis brauchen, laufen außerhalb der GitHub-CI **nirgends** mit ihrem Dienst, sondern
überspringen sich still:
- der Migrations-Smoke des Monitorings,
- `test_stream_redis`,
- der TOCTOU-Test des ca-issuers.

## Ziel & Nicht-Ziele

**Ziel:**
- Die Roadmap hat ein Skript mit Historie: jede Schreiboperation unter `flock`, mit `.bak`, geprüfter
  Zeilenzahl und einem lokalen Commit.
- Jede Einheit hat einen Zustand; die Abschnitte folgen dem Status.
- `/plan` hat einen Kurz- und einen Bündel-Modus.
- Beweise haben eine feste Form.
- Der Wochenlauf liefert JUnit.
- Die drei Tests laufen im Integration-Layer gegen den Compose-Stack und sind dort Pflicht.

**Nicht-Ziele:**
- Kein `$/Task` in `roadmap.py stats`: Das braucht die `total_cost_usd` der Worker-Läufe, und die gibt es erst ab
  Stufe 7 (Entscheidung am Gate).
- Kein `verified`, `archive`, `expire`, `rebuild`, `set` in `roadmap.py`; das Roadmap-Dokument hat sie gestrichen.
- Kein Umbau des Abschnitts „Als Nächstes“: Den kuratiert Kevin von Hand, das Skript liest ihn nur.
- Kein gotestsum, cargo-nextest, vitest-junit oder `lib_junit.sh`. JUnit gibt es nur dort, wo der Wochenlauf es
  braucht.
- Keine Änderung am Produktions-`docker-compose.yml`.

## Betroffene Komponenten & Dateien

**5a — Roadmap als Skript** (Komponente `scripts`):
- `scripts/dev/roadmap.py` (neu, nur Python-Stdlib) mit Tests in `scripts/dev/tests/test_roadmap.py` (neu) und
  einem eigenen pytest-Schritt in `scripts/tests/run.sh`.
- `scripts/tests/heavy.sh`: `roadmap_append` wird durch `roadmap.py add` ersetzt; Tests in `heavy_test.sh`.
- `scripts/dev/hooks/session-status.sh`: WIP-Deckel und alle Punkte von „Als Nächstes“.
- `.claude/skills/roadmap/SKILL.md` (neu).

**5b — Planen und Beweis** (Komponente `scripts` plus Skill-Texte):
- `.claude/skills/feature-plan/SKILL.md`, `.claude/skills/feature-build/SKILL.md`, `AUTONOMOUS.md`.
- `tasks/README.md`, `tasks/templates/task.md`, `scripts/dev/ledger.sh` (Lint der neuen Felder), `ledger_test.sh`.
- `docs/developer/cicd.html` und `docs/en/developer/cicd.html` (Beweis-Konvention).

**5c — Test-Ausgaben und Pflicht-Tests** (Test-Infrastruktur):
- `scripts/tests/run.sh` (JUnit-Flag der pytest-Schritte, neuer Integrations-Schritt), `scripts/tests/heavy.sh`
  (JUnit sammeln).
- `apps/web/playwright.config.ts` (JUnit-Reporter, Projekt `live`) und neue Specs unter `apps/web/tests/live/`.
- `apps/desktop/e2e/wdio.conf.js` und `apps/desktop/e2e/package.json` (`@wdio/junit-reporter`).
- `docker-compose.test.yml` (Postgres und Redis auf 127.0.0.1) und `scripts/tests/lib_e2e_stack.sh`.
- `apps/server/tests/test_stream_redis.py`: die Redis-URL kommt aus der Umgebung, Default wie heute.

## Datenmodell / Formate

**ROADMAP.md bleibt Markdown**, lesbar und von Hand editierbar. `roadmap.py` liest und schreibt dieselben zehn
Spalten (`ID | Klasse | Titel | Status | Quelle / Beweis | Ledger | Hängt ab von | PR | Ablauf | Kevin-min`) in
den bestehenden Abschnitten.

- **Status und Abschnitt:**
  - `neu` → „Neu (untriagiert)“;
  - `geplant`, `freigegeben` → „Geplant“;
  - `aktiv`, `bereit`, `pr` → „In Arbeit“;
  - `zurückgestellt` → „Zurückgestellt“;
  - `blockiert` → „Blockiert“;
  - `abgeschlossen`, `abgelehnt` → „Abgeschlossen“, nach 30 Tagen „Archiv“.
  - Die Alias-Werte `geparkt` und `erledigt` werden beim Lint gemeldet.
- **Dedup-Schlüssel:** keine neue Spalte, damit keine Migration aller Zeilen nötig wird. Der Schlüssel steht als
  Token `Dedup-Key: <klasse>:<komponente>:<datei>:<symbol>` am Ende der Spalte „Quelle / Beweis“. `add` verweigert
  einen Schlüssel, den eine offene Zeile schon trägt.
- **ID-Vergabe:** höchste `R-nnnn` über alle Zeilen plus eins, unter `flock`. Doppelte IDs sind ein Lint-Fehler.
- **Kopfzeile** (`Stand … · WIP: …`): `roadmap.py` rechnet sie bei jedem Schreiben neu.
- **Ledger-Kopf (5b):** Das Feld `Heavy: none | linux-full | scenario <flags> | windows` ersetzt
  `Fast-Suite:`/`Warm-Profil:` für neue Ledger. `feature-build`, `lane.sh` und `ledger.sh` lesen die alten Felder
  weiter, solange es Ledger mit ihnen gibt (Entscheidung am Gate).
- **Status-Folge der Ledger:** `geplant` → `freigegeben` (Kevins Freigabe) → `aktiv` (Bau läuft) → `bereit`
  (PR-reif) → `erledigt` (PR offen oder gemergt) | `blockiert`. Interaktiv startet `feature-build` weiterhin auch
  `geplant` mit ausdrücklichem Pfad. Der Worker (Stufe 7) nimmt nur `freigegeben`.
- **Beweisklassen A–D (5b):** Zu einer Task gehören optional folgende Zeilen:
  - `Beweis:` (Branch + SHA + Kommando + erwartete Ausgabe),
  - `Orakel:` (crash|contract|property|differential|mutation-sample|coverage|analyzer|metric),
  - `Refuter:`,
  - `Dedup-Key:`,
  - `Metrik:` (Klasse B),
  - `Kosten:`,
  - `HEAD:`.

  `ledger.sh lint` prüft ihre Form. `/plan --kurz` verlangt die Zeile `Semantik:` gegen `docs/`.

## Externe Integrationen

- **Playwright:** Reporter `['junit', { outputFile }]` und Projekte laut offizieller Doku
  (playwright.dev/docs/test-reporters). Vor dem Bau per WebFetch nachlesen; bis dahin nicht verifiziert.
- **WebdriverIO:** Paket `@wdio/junit-reporter` mit `outputDir` laut webdriver.io/docs/junit-reporter. Die Version
  wird zur installierten `@wdio/cli` passend gepinnt; ebenfalls vor dem Bau nachlesen.
- **pytest:** `--junitxml=<pfad>` ist ein eingebautes Flag.

## Trade-offs & Alternativen

1. **Ein Ledger oder drei:** drei, entschieden am Gate. 5a zuerst: 5a und 5c berühren beide `heavy.sh`. Danach
   laufen 5b (Skills und Doku) und 5c (Test-Infrastruktur) disjunkt und können parallel als zwei Lanes laufen.
2. **Dedup-Key als Spalte oder als Token:** Token. Eine elfte Spalte hieße, 80 Zeilen zu migrieren und jede
   Hand-Bearbeitung breiter zu machen.
3. **Die Pflicht-Tests gegen den Stack:** Ports nur im Test-Override, entschieden am Gate. Die Alternative
   `docker compose run` im Stack-Netz bräuchte ein Test-Image.
4. **`stats` schlank:** entschieden am Gate. Enthalten sind Tasks/Tag, Kevin-min/PR, Wartezeit je Zustand und die
   Dedup-/Stale-Quote. `$/Task` folgt mit Stufe 7.

## Risiken & Rollback

- **Hand-Edit und Skript gleichzeitig.** Gegenmittel: `flock`, `.bak` und eine Zeilenzahl-Invariante. Schreibt
  jemand parallel von Hand, verweigert das Skript mit einer klaren Meldung, statt zu überschreiben.
- **Die erste Bereinigung der echten ROADMAP.md** (R-0047 doppelt, Zeilen im falschen Abschnitt) ändert Kevins
  Datei. Sie läuft als eigener Schritt am Ende von 5a, mit Diff zur Ansicht vor dem Commit im privaten Repo.
- **Reporter-Flags stimmen nicht mit der Doku überein.** Die Doku wird vor dem Bau per WebFetch gelesen, und der
  Abschluss-Beweis von 5c zeigt die XMLs real.
- **Rollback:** jeder Task ein Commit, `git revert` je Task. Für das private Repo gibt es `.bak` und die
  git-Historie.

## Doku-Impact

- **5a:** `DEVELOPMENT.md` (`roadmap.py`, der neue pytest-Schritt), `AUTONOMOUS.md` (Roadmap-Pflege).
- **5b:** `tasks/README.md`, `AUTONOMOUS.md`, `docs/developer/cicd.html` DE+EN (Beweis-Konvention).
- **5c:** `DEVELOPMENT.md` (JUnit-Ort, Stack-Ports), `docs/developer/cicd.html` DE+EN (was der Integration-Layer
  als Pflicht prüft), CHANGELOG (Test-Infrastruktur, nicht nach außen sichtbar: nur „Changed“ für Entwickler).

## Entschieden am Gate (Kevin, 2026-09-23)

1. Drei Ledger 5a/5b/5c; 5a zuerst, danach 5b und 5c parallel.
2. `Heavy:` ersetzt `Fast-Suite:`/`Warm-Profil:` mit Kompatibilität.
3. `roadmap.py stats` schlank; `$/Task` mit Stufe 7.
4. Die Pflicht-Tests laufen gegen Postgres und Redis des Stacks, veröffentlicht nur im Test-Override.

## Offene Fragen

Keine. **Freigegeben am 2026-09-25 (Kevin): alle drei Ledger, 5a zuerst.**
