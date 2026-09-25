---
name: feature-plan
description: Plane ein neues Feature/Change und zerlege es in eine Spec + eine Ledger aus kleinen, autonom abarbeitbaren Tasks. Nutzen, wenn ein nicht-triviales Vorhaben startet ("ich will Feature X", "baue Y ein", "plane Z"), BEVOR Code entsteht. Endet an einem Design-Gate zur menschlichen Freigabe — implementiert selbst nichts. Mit --kurz R-nnnn ein Kurz-Ledger aus einer belegten Roadmap-Zeile, mit --bundle <komponente> die REF-Zeilen einer Komponente als Sammel-Ledger.
---

# Feature planen & in autonome Tasks zerlegen

Diese Phase macht aus einer Idee zwei Artefakte: eine **Spec** und eine **Task-Ledger**
aus so kleinen, unabhängig verifizierbaren Aufgaben, dass die Build-Phase sie ohne
Rückfragen abarbeiten kann. **Am Ende: Design-Gate — stoppen, auf Freigabe warten.
In dieser Phase entsteht KEIN Produktivcode.** Spec und Ledger werden am Gate der erste
Commit auf dem Feature-Branch (R-0065); einen anderen Branch-Schritt gibt es hier nicht.

**Drei Aufrufe:** `/feature-plan <idee>` — der volle Weg mit Spec (Abschnitte 1–4);
`/feature-plan --kurz R-nnnn` — ein Kurz-Ledger aus einer Roadmap-Zeile, ohne Spec (3a);
`/feature-plan --bundle <komponente>` — REF-Zeilen einer Komponente in einem Sammel-Ledger
(3a). Alle drei enden am selben Design-Gate (4). Eine SEC-Zeile plant keiner der drei Wege: das
Gate committet in dieses öffentliche Repo, SEC-Funde bleiben unter `tasks/private/` (3a).

Modell: **mindestens Opus** — die Planung selbst läuft auf Opus oder Fable, und auch die Explorer-
und Verifikations-Subagenten dieser Phase werden mit `model: opus` gestartet (Kevin, 2026-09-18: eine
falsche Annahme in der Spec kostet mehr als ein teurer Explorer). Sonnet ist nur für die schnellen
Task-Reviewer in `feature-build` vorgesehen. Sprache: Deutsch, Bezeichner im Original (CLAUDE.md).

## 0. Interaktiv arbeiten (diese Phase ist ein Dialog, kein Alleingang)
Planen ist **interaktiv**. Sobald eine echte Mehrdeutigkeit auftaucht, die die Spec
verändert (Scope, gewünschtes Verhalten, betroffene Komponente, Trade-off-Wahl), **frag
sofort per `AskUserQuestion`** — nicht still entscheiden, nicht nur ans Gate schieben. Eine
falsche Annahme früh kostet die ganze Spec. Faustregel: Implementierungsdetails darfst du
selbst wählen; alles, was das *Was* oder das sichtbare Verhalten betrifft, wird gefragt.
Bündle 2–4 Fragen pro Runde, mit einer Empfehlung als erster Option.

## 1. Verstehen & explorieren
- Kommt das Vorhaben aus der Roadmap (`R-nnnn`), zuerst die Zeile lesen:
  `python3 scripts/dev/roadmap.py show R-nnnn` (Quelle, Beweis, Abhängigkeiten, Dedup-Key).
- Kläre die Idee so weit, dass **Scope** und **Erfolgskriterium** klar sind — per Rückfrage
  (siehe 0.), wo nötig. Echte Produktentscheidungen (nicht Implementierungsdetails) NICHT
  still treffen (CLAUDE.md: „Mehrdeutigkeit ansprechen").
- Exploriere die betroffenen Komponenten (Explore-Agenten oder direkt lesen): welche
  `apps/*`, welche Module, welche API-Routen / Pydantic-Schemas / DB-Tabellen / UI-Seiten /
  Rust-Commands / Go-Pakete. **Nenne konkrete Dateien**, keine Vermutungen.
- Schlage in `docs/` nach, wie sich Bestehendes verhält (Projektregel: im Zweifel dort
  zuerst). Wird ein externes Wire-Protokoll berührt (**FRP**, **Tauri**, **VictoriaMetrics**),
  ziehe die offizielle Doku via `WebFetch` (CLAUDE.md: „verifizieren statt fabulieren").

## 2. Spec schreiben → `docs/features/<slug>.md`
Slug = kurz, kebab-case. Abschnitte:
- **Problem / Motivation** — warum überhaupt.
- **Ziel & Nicht-Ziele** — was rein, was bewusst raus (YAGNI).
- **Betroffene Komponenten & Dateien** — konkrete Pfade.
- **Datenmodell / API / Migrationen** — neue Felder/Endpunkte; Alembic-Migration nötig?
  Vertrags-Drift zwischen Server ↔ Web ↔ Desktop ↔ Agent bedacht?
- **Externe Integrationen** — FRP/Tauri/VM, mit Doku-Link falls verifiziert.
- **Trade-offs & Alternativen** — kurz, mit Empfehlung + Begründung.
- **Risiken & Rollback** — was kann brechen, wie nimmt man es zurück.
- **Doku-Impact (kurz, mit Augenmaß)** — in 1–2 Sätzen festhalten, was diese Änderung an
  Doku *wirklich* braucht, **proportional zum Umfang**. Nennenswerte, nach außen sichtbare
  Änderungen gehören dokumentiert (`docs/` DE+EN, ggf. `README.md`/`CHANGELOG.md`): neue/
  geänderte Features, API/Endpunkte, CLI-Flags, Env-Variablen, Ports, Config-/Wire-Formate,
  Betriebs-/Installations-Schritte, Architektur/Datenflüsse. **Bugfixes, Kleinkram und rein
  internes Refactoring brauchen keine Doku** — dann einfach „keine". Keine Doku-Arbeit künstlich
  erzeugen (YAGNI); im Zweifel die betroffene Doku-Stelle kurz aufschlagen und entscheiden.
- **Offene Fragen** — alles, was am Design-Gate entschieden werden muss.

## 3. Ledger schreiben → `tasks/<slug>.md`
**Immer eine eigene Datei pro Vorhaben unter `tasks/`** — nie an eine Sammel-Datei anhängen
(Konvention: `tasks/README.md`). Format durable, von oben nach unten abarbeitbar. Kopf:

```
# <Feature> — Task-Ledger
Status: geplant · Branch: feature/<slug> · Commit-Granularität: pro Task · Review: pro Task (feature-review) · Modell: Opus
Spec: docs/features/<slug>.md (Roadmap R-nnnn)
Heavy: none — <warum keine schwere Suite>
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung
```
(`Spec:` = Rück-Link zur Soll-Vorgabe, die `feature-build`/`feature-review` als Referenz
nutzen; bei einem Report-Backlog zeigt das Feld auf den Report statt auf eine Spec. Die
Roadmap-ID dahinter ist die Zeile, die das Gate anlegt (4) und der `feature-build` den Status
nachzieht — ohne sie bleibt die Zeile über Bau und PR hinweg stehen.)
(`Status:` = Ledger-Zustand in der Folge `geplant` → `freigegeben` → `aktiv` → `bereit` →
`erledigt`, daneben `blockiert` (tasks/README.md). `feature-plan` schreibt `geplant`; Kevins
Freigabe am Gate macht daraus `freigegeben`, der Start von `/feature-build` `aktiv`. Nicht mit
dem Task-Status `[ ]`/`[x]` verwechseln.)
(`Review:` = wann der Frischer-Kontext-Review läuft. `pro Task (feature-review)` ist der
Default. Ein **Kurz-Ledger** mit **≤ 3 Tasks** bekommt stattdessen `Review: am Ende` —
`feature-build` fährt dann genau **einen** Review über den ganzen Branch-Diff und lässt den
abschließenden `/code-review` weg; bei drei kleinen Tasks sähe der zweite Durchgang nur
denselben Diff noch einmal.)
(`Heavy:` = welche schwere Suite der Abschluss braucht, aus „Betroffene Komponenten" der
Spec abgeleitet, nach ` — ` die Begründung (tasks/README.md):
`none` = keine, der Diff berührt keinen Stack-, Gateway-, PKI- oder Install-Pfad;
`linux-full` = `run.sh integration` (und `e2e` bei einer berührten Web- oder Desktop-Journey)
auf einer Pool-VM — Server-API/Gateway, `apps/ca-issuer`, `apps/agent`, Desktop-Journeys
(Connect/Tunnel/Enrollment-UI, `apps/desktop/e2e/*.live.js`), `docker-compose*.yml`;
`scenario <flags>` = ein Multibox-Lauf, wenn die Spec **Cross-Host-Pfade** berührt
(FRP-Tunnel-Datenpfad, :8444-Provisioning, `build-deb.sh`/`build-rpm.sh`,
`scripts/install|update`, mTLS/PKI), nur die passenden Flags (`--tunnel`, `--agents 1`,
`--rpm`, `--enforce`) — der Lauf bleibt ask-first, `feature-build` fragt am Ende;
`windows` = die Windows-VM (Stufe 12). Die älteren Felder `Fast-Suite:`/`Warm-Profil:` und die
Zeile `Abschluss: multibox` schreibt ein neues Ledger nicht mehr; `ledger.sh lint` meldet
beide Formen zugleich als Fehler.)

**Task-Größe = autonomietauglich** (die wichtigste Regel dieser Phase):
- Eine Task ≈ **eine fokussierte Änderung**, möglichst **eine Komponente**, ≤ ~3 Dateien.
- Jede Task hat ein **`Verify:`** — ein konkreter Befehl/Assertion, der grün/rot sagt.
  Kein „sieht gut aus". **Nur in Flag-Form**, ohne Env-Präfix, weil eine Allow-Regel nie
  über eine Variablenzuweisung matcht: `bash scripts/dev/verify.sh <komponente> --strict
  [-- <args>]` oder `bash scripts/tests/run.sh <layer> --strict --only <keys…>`. Env-Bedarf
  (`DATABASE_URL`, `AH_TEST_DB`, PATH) löst das Skript auf, nicht der Aufrufer. Schwere
  Läufe stehen als eigene `Heavy:`-Zeile im Ledger-Kopf, nie in einer Task.
- Jede Task ist **unabhängig testbar**; Reihenfolge nur bei echter Abhängigkeit.
- Steckt in einer Task eine **Design-Entscheidung**, ist sie zu groß → Entscheidung
  gehört in die Spec (offene Frage), nicht in die Task.
- Neue Datei ⇒ Task nennt den **SPDX-Header**. Neuer Flow/Journey ⇒ Task **enthält den Test**
  (Unit bzw. E2E-Ebene laut CLAUDE.md).
- **Doku im `Doku:`-Feld, nach Augenmaß:** Trägt eine Task eine nennenswerte sichtbare
  Änderung, nennt das Feld die zu aktualisierenden Stellen (`docs/` DE+EN, ggf. README/
  CHANGELOG); die meisten Tasks sind schlicht `Doku: keine (intern)`. Passt zum `Doku-Impact`
  der Spec — ohne Doku künstlich aufzublähen.

Task-Schema:
```
### T<n> — <Titel>  [ ]
Komponente: apps/… · Dateien: …
Änderung: <was genau, 1–3 Sätze>
Verify: bash scripts/dev/verify.sh <komponente> --strict     (oder: bash scripts/tests/run.sh <layer> --strict --only <keys…>)
Doku: <docs/… DE+EN · README · CHANGELOG  |  keine (intern)>
Abhängt von: T<k>   (nur falls nötig)
```

## 3a. Die kurzen Wege: `--kurz` und `--bundle`

**`--kurz R-nnnn`** — für einen belegten Fund, vor allem REG und BUG:
- **Nicht für SEC:** Eine SEC-Zeile wird **verweigert, mit Grund**: SEC-Funde bleiben unter
  `tasks/private/` (Roadmap-Dokument 3.3.3), und das Gate committet das Ledger in dieses
  öffentliche Repo. Einen privaten Kurz-Weg gibt es noch nicht; bis dahin plant Kevin SEC von Hand.
- `python3 scripts/dev/roadmap.py show R-nnnn` lesen. Die Zeile muss einen Beweis tragen
  (`Quelle / Beweis` mit Branch@SHA, Kommando oder Lauf). Steht dort „Beweis fehlt" oder nichts
  Nachprüfbares: **stopp**, das sagen und den vollen Weg oder zuerst einen Beweis vorschlagen —
  ein Kurz-Ledger ohne Beweis ist eine Vermutung.
- Keine Spec. Das Ledger bekommt **1–3 Tasks**, `Review: am Ende`, `Spec: Roadmap R-nnnn`, den
  Kopf aus Abschnitt 3 mit `Heavy:`. Braucht der Fund erkennbar mehr als drei Tasks: **stopp**,
  das sagen und den vollen Weg vorschlagen — ein Kurz-Ledger, das man zusammenstauchen muss,
  ist keins.
- Jede Task trägt die Zeilen der Beweis-Konvention (tasks/README.md), soweit die Zeile sie
  hergibt: `Beweis:` aus der Zeile (Branch + SHA + Kommando + erwartete Ausgabe), `Dedup-Key:`
  und `HEAD:`, wenn bekannt. Die Fix-Task verifiziert mit genau dem Test, der den Fund zeigt.
- **Pflicht: `Semantik:`** — die Stelle unter `docs/`, die das gewollte Verhalten beschreibt,
  mit Datei und wörtlichem Zitat (vorher lesen, nicht erinnern). Beschreibt die Doku das
  heutige Verhalten als Absicht, ist es kein Fehler: dann kein Fix-Task, sondern eine offene
  Frage an Kevin, sofort gestellt (Abschnitt 0). Es entsteht kein Ledger und kein Plan-Branch;
  die Zeile behält ihren Status und hält die Frage in ihrer Notiz fest, hinter der bisherigen,
  denn `--note` ersetzt sie: `roadmap.py status R-nnnn <status> --note "<bisherige Notiz>;
  Semantik-Frage: …"`. Erst Kevins Antwort macht wieder einen Plan daraus.
  Findet sich keine Stelle, steht `Semantik: keine Stelle in docs/ — <was gesucht wurde>`, und
  die Lücke gehört in die offenen Fragen am Gate.

**`--bundle <komponente>`** — Aufräumarbeit einer Komponente in einem Rutsch:
- Nur Klasse **REF**. Aus `roadmap.py show` die `neu`- und `geplant`-Zeilen mit Klasse REF
  sammeln, deren Komponente passt (`roadmap.py show R-nnnn`: die Komponente im vollen
  Dedup-Key, sonst das Ledger oder Titel und Quelle). Andere Klassen werden **verweigert, mit
  Grund**: ein Fehler (REG, BUG) braucht seinen eigenen Beweis und sein Kurz-Ledger, ein SEC
  den Weg von Hand (siehe `--kurz`), ein REL seinen eigenen Pfad zum Release, ein FEAT eine Spec.
- Ein Sammel-Ledger mit **höchstens 15 Tasks**, eine Task je Zeile (zwei Zeilen an derselben
  Stelle dürfen eine Task sein). Mehr Zeilen: die ersten 15 in der Reihenfolge der Datei, der
  Rest bleibt `neu` und wird am Gate genannt. Der Kopf aus Abschnitt 3 mit `Heavy:`,
  `Spec: Roadmap R-a, R-b, …`; `Review: pro Task`, bei höchstens drei Tasks `am Ende`.
- Jede Task nennt ihre Roadmap-ID und trägt, was die Beweis-Konvention für ihre Klasse verlangt
  (bei REF meist Klasse B oder C: `Metrik:`, `Orakel:`).

Beide Wege enden am **selben Gate** (4): Roadmap-Zeilen auf `geplant`, der Plan als erster
Commit auf `feature/<slug>`, Präsentation, Freigabe nur mit Kevins Wort. Beim Bündel gilt jeder
Roadmap-Schritt des Gates **für jede enthaltene Zeile**: `roadmap.py status R-x geplant --ledger
tasks/<slug>.md` je Zeile, und bei der Freigabe `roadmap.py approve R-x` je Zeile (beide Verben
nehmen genau eine ID). Eine vergessene Zeile bliebe in der Roadmap offen, obwohl sie gebaut ist.

## 4. Design-Gate — STOPP
- **Zeilenangaben frisch:** Jede `datei:zeile` in Spec und Ledger unmittelbar vor dem
  Schreiben neu greppen — ein früher Explorer-Lauf oder ein Merge dazwischen verschiebt sie.
- **Roadmap vor dem Präsentieren:** Hat das Vorhaben noch keine Zeile, trägt das Gate sie
  ein — `python3 scripts/dev/roadmap.py add --class <K> --title "…" --source "kevin <datum>"
  --ledger tasks/<slug>.md` (druckt die ID) — und setzt sie auf `geplant`:
  `roadmap.py status R-nnnn geplant`. Eine bestehende `neu`-Zeile, oder eine schon `geplant`e
  (etwa in `/roadmap` angenommen), wird `roadmap.py status R-nnnn geplant --ledger
  tasks/<slug>.md` — der Pfad gehört in die Spalte `Ledger`, dort lesen ihn `next` und die
  Parallel-Prüfung; derselbe Status füllt nur die Spalte. Nie ein Edit an der Datei.
- **Plan auf den Branch (R-0065):** `git switch -c feature/<slug> main`, Spec und Ledger
  committen (Ledger mit `Status: geplant`), zurück mit `git switch main` — der Haupt-Checkout
  bleibt auf `main`. Die Commit-Nachricht ist `chore(plan): add spec + ledger for <slug>`, bei
  `--kurz` und `--bundle` ohne Spec `chore(plan): add ledger for <slug>`. Worktrees und der
  Worker sehen nur Committetes, und `lane.sh new` sucht den Plan genau dort.
- Präsentiere im Chat: **1 Absatz** Zusammenfassung, die **Task-Liste** (Titel + Verify),
  und **alle offenen Fragen** klar herausgestellt.
- **Parallel-Tauglichkeit prüfen — gegen alle `aktiv`- und `freigegeben`-Zeilen:**
  `roadmap.py show` listet sie („In Arbeit", „Geplant"), dazu `bash scripts/dev/lane.sh list`.
  Für jede Zeile ihr Ledger lesen — ein geplantes Ledger liegt bis zum Merge nur auf seinem
  Branch (R-0065): `git show <branch>:tasks/<slug>.md`, den Branch nennen `lane.sh list` oder
  `git branch --list 'feature/*'`; `next --exclude-components` sieht es dort noch nicht
  (R-0099) — und prüfen, ob dieses Vorhaben disjunkt ist: Komponenten
  (die `Komponente:`-Zeilen beider Ledger) und geteilte Contract-Dateien (API-Routen/
  Pydantic-Schemas, DB-Migrationen, FRP-Config-Format, Tauri-Commands, `run.sh`/`ci.yml`,
  primäre `docs/`-Seiten). Ergebnis am Gate je Zeile: „parallel-tauglich zu R-nnnn: ja/nein —
  <Grund>". Überlappt es → **warnen** und seriell empfehlen, nicht parallel.
- **Lanes aktiv vorschlagen (Kevin, 2026-09-18).** Ist das Vorhaben disjunkt zu einem anderen
  `freigegeben`- oder `aktiv`-Ledger (Komponenten, Contracts, `run.sh`/`ci.yml`-Stellen, primäre
  Doku-Seiten) **und** braucht höchstens eines der beiden VMs **und** teilen sie sich keine
  Test-Datenbank (zwei Server-Suiten gleichzeitig zerstören sich das Ergebnis), dann steht am
  Gate nicht nur „parallel-tauglich: ja", sondern der fertige Lane-Start:
  ```
  bash scripts/dev/lane.sh new <slug>          # Worktree auf feature/<slug>, der Plan ist schon drin
  cd ../AdminHelper-<slug> && claude          # dort: /feature-build tasks/<slug>.md
  ```
  Dazu ein Satz zu den Grenzen: beide Opus-Bauten teilen sich Kevins Nutzungsfenster, der
  zweite PR muss rebasen (CHANGELOG, DEVELOPMENT.md), und Kevins Review-Zeit bleibt der
  Engpass. Die Lane ist die Ausnahme vom Deckel „genau ein Bau aktiv" (CLAUDE.md §2) — nicht
  der Default, sondern ein Vorschlag, den Kevin annimmt oder nicht.
- Sage explizit: „Bitte `docs/features/<slug>.md` und `tasks/<slug>.md` auf `feature/<slug>`
  prüfen/anpassen. Zum Bauen nach der Freigabe: **`/feature-build tasks/<slug>.md`** auf
  `feature/<slug>` in einer Opus-Session — oder als parallele Lane
  **`bash scripts/dev/lane.sh new <slug>`** (AUTONOMOUS.md „Parallel-Betrieb")."
- **Die Freigabe** ist Kevins Wort (nächster User-Turn). Dann und nur dann:
  `python3 scripts/dev/roadmap.py approve R-nnnn` und ein Commit auf `feature/<slug>`, der den
  Ledger-Kopf auf `Status: freigegeben` setzt (`chore(plan): approve <slug>`). Ohne sein
  Wort bleibt beides `geplant`.
- **Implementiere nichts.** Diese Phase endet hier: kein Produktivcode, kein weiterer Branch,
  nichts auf `main`.
