---
name: feature-plan
description: Plane ein neues Feature/Change und zerlege es in eine Spec + eine Ledger aus kleinen, autonom abarbeitbaren Tasks. Nutzen, wenn ein nicht-triviales Vorhaben startet ("ich will Feature X", "baue Y ein", "plane Z"), BEVOR Code entsteht. Endet an einem Design-Gate zur menschlichen Freigabe — implementiert selbst nichts. Mit --kurz R-nnnn ein Kurz-Ledger aus einer belegten Roadmap-Zeile, mit --bundle <komponente> die REF-Zeilen einer Komponente als Sammel-Ledger.
---

# Feature planen & in autonome Tasks zerlegen

Diese Phase macht aus einer Idee zwei Artefakte: eine **Spec** und eine **Task-Ledger**
aus so kleinen, unabhängig verifizierbaren Aufgaben, dass `/feature-build` sie ohne
Rückfragen abarbeiten kann. **Am Ende: Design-Gate — stoppen, auf Freigabe warten.
In dieser Phase entsteht KEIN Produktivcode.** Spec und Ledger werden am Gate der erste
Commit auf dem Feature-Branch (R-0065).

**Drei Aufrufe:** `/feature-plan <idee>` — der volle Weg mit Spec (Abschnitte 1–4);
`/feature-plan --kurz R-nnnn` — ein Kurz-Ledger aus einer Roadmap-Zeile, ohne Spec (3a);
`/feature-plan --bundle <komponente>` — REF-Zeilen einer Komponente in einem Sammel-Ledger
(3a). Alle drei enden am selben Design-Gate (4). Eine SEC-Zeile plant keiner der drei Wege: das
Gate committet in dieses öffentliche Repo, SEC-Funde bleiben unter `tasks/private/` (3a).

Modell: **mindestens Opus**, auch für Explorer- und Verifikations-Subagenten dieser Phase
(`model: opus`; Kevin, 2026-09-18). Sprache: Deutsch, Bezeichner im Original (CLAUDE.md).

## 0. Interaktiv arbeiten
Sobald eine echte Mehrdeutigkeit auftaucht, die die Spec verändert (Scope, gewünschtes
Verhalten, betroffene Komponente, Trade-off-Wahl), **frag sofort per `AskUserQuestion`**,
2–4 Fragen je Runde, Empfehlung als erste Option. Implementierungsdetails wählst du selbst;
alles, was das *Was* oder das sichtbare Verhalten betrifft, wird gefragt.

## 1. Verstehen & explorieren
- Kommt das Vorhaben aus der Roadmap (`R-nnnn`), zuerst die Zeile lesen:
  `python3 scripts/dev/roadmap.py show R-nnnn` (Quelle, Beweis, Abhängigkeiten, Dedup-Key).
- Scope und Erfolgskriterium klären; Produktentscheidungen nicht still treffen.
- Betroffene Komponenten explorieren (Explore-Agenten oder direkt lesen) und **konkrete Dateien
  nennen**: Module, API-Routen, Pydantic-Schemas, DB-Tabellen, UI-Seiten, Rust-Commands, Go-Pakete.
- In `docs/` nachschlagen, wie sich Bestehendes verhält. Berührt das Vorhaben ein externes
  Wire-Protokoll (**FRP**, **Tauri**, **VictoriaMetrics**), die offizielle Doku per `WebFetch` lesen.

## 2. Spec schreiben → `docs/features/<slug>.md`
Slug = kurz, kebab-case. Abschnitte: **Problem / Motivation** · **Ziel & Nicht-Ziele** (YAGNI) ·
**Betroffene Komponenten & Dateien** · **Datenmodell / API / Migrationen** (Alembic? Vertrags-Drift
Server ↔ Web ↔ Desktop ↔ Agent?) · **Externe Integrationen** (mit Doku-Link) · **Trade-offs &
Alternativen** (mit Empfehlung) · **Risiken & Rollback** · **Doku-Impact** (1–2 Sätze, proportional:
sichtbare Änderungen DE+EN, Bugfixes und internes Refactoring „keine“) · **Offene Fragen**.

## 3. Ledger schreiben → `tasks/<slug>.md`
Immer eine eigene Datei pro Vorhaben (Format: `tasks/README.md`). Kopf:

```
# <Feature> — Task-Ledger
Status: geplant · Branch: feature/<slug> · Review: pro Task
Spec: docs/features/<slug>.md (Roadmap R-nnnn)
Heavy: none — <warum keine schwere Suite>
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung
```
`Review: am Ende` für ein **Kurz-Ledger** mit ≤ 3 Tasks (ein Review über den Branch-Diff).
`Heavy:` aus „Betroffene Komponenten“ der Spec, nach ` — ` die Begründung: `none` (kein Stack-,
Gateway-, PKI- oder Install-Pfad); `linux-full` (Server-API/Gateway, `apps/ca-issuer`, `apps/agent`,
Desktop-Journeys, `docker-compose*.yml`); `scenario <flags>` (Cross-Host: FRP-Tunnel-Datenpfad,
:8444-Provisioning, `build-deb.sh`/`build-rpm.sh`, `scripts/install|update`, mTLS/PKI; nur die
passenden Flags, bleibt ask-first); `windows` (die Windows-VM).

**Task-Größe = autonomietauglich:**
- Eine Task ≈ eine fokussierte Änderung, möglichst eine Komponente, ≤ ~3 Dateien.
- Jede Task hat ein **`Verify:`** in Flag-Form ohne Env-Präfix:
  `bash scripts/dev/verify.sh <komponente> --strict [-- <test>]`. Schwere Läufe stehen in `Heavy:`,
  nie in einer Task.
- Jede Task ist unabhängig testbar; Reihenfolge nur bei echter Abhängigkeit.
- Steckt in einer Task eine Design-Entscheidung, gehört sie als offene Frage in die Spec.
- Neue Datei ⇒ die Task nennt den SPDX-Header. Neuer Flow ⇒ die Task enthält den Test.
- `Doku:` nach Augenmaß; die meisten Tasks sind `Doku: keine (intern)`.
- `Komponente:` ist der Name aus `verify.sh` (`server`, `web`, `desktop-ui` …), kein Pfad: `task-close.sh`
  vergleicht ihn wörtlich mit den Komponenten des `Verify:`.

Task-Schema:
```
### T<n> — <Titel>  [ ]
Komponente: <komponente> · Dateien: …
Änderung: <was genau, 1–3 Sätze>
Verify: bash scripts/dev/verify.sh <komponente> --strict
Doku: <docs/… DE+EN · README · CHANGELOG  |  keine (intern)>
Abhängt von: T<k>   (nur falls nötig)
Test-Löschung: <datei>::<test> — <Grund>   (nur falls nötig; ganze Datei: <datei>::*)
```
Löscht eine Task einen Test oder eine Testdatei, kündigt der Plan das an (`tasks/README.md`): die
Ankündigung zählt nur committet, und der Plan-Commit am Gate ist der Weg dorthin.

## 3a. Die kurzen Wege: `--kurz` und `--bundle`

**`--kurz R-nnnn`** — für einen belegten Fund, vor allem REG und BUG:
- **Nicht für SEC** (verweigern, mit Grund): das Gate committet ins öffentliche Repo.
- Die Zeile muss einen Beweis tragen (`Quelle / Beweis` mit Branch@SHA, Kommando oder Lauf); fehlt er:
  stopp, den vollen Weg oder zuerst einen Beweis vorschlagen.
- Keine Spec; 1–3 Tasks, `Review: am Ende`, `Spec: Roadmap R-nnnn`, Kopf wie in 3 mit `Heavy:`. Braucht
  der Fund erkennbar mehr als drei Tasks: stopp, den vollen Weg vorschlagen.
- Jede Task trägt `Beweis:` aus der Zeile, `Dedup-Key:` und `HEAD:`, wenn bekannt (Beweis-Konvention,
  `tasks/README.md`); die Fix-Task verifiziert mit genau dem Test, der den Fund zeigt.
- Nennt die Zeile schon ein Ledger (Spalte `Ledger`), darauf aufbauen oder Kevin fragen.
- **Pflicht: `Semantik:`** — die Stelle unter `docs/`, die das gewollte Verhalten beschreibt, mit Datei
  und wörtlichem Zitat. Beschreibt die Doku das heutige Verhalten als Absicht, ist es kein Fehler: kein
  Ledger, sondern eine sofortige Frage an Kevin; die Zeile behält ihren Status und hält die Frage in der
  Notiz fest (`--note` ersetzt: `roadmap.py status R-nnnn <status> --note "<bisherige Notiz>;
  Semantik-Frage: …"`). Findet sich keine Stelle: `Semantik: keine Stelle in docs/ — <was gesucht
  wurde>`, und die Lücke gehört in die offenen Fragen am Gate.

**`--bundle <komponente>`** — Aufräumarbeit einer Komponente in einem Rutsch:
- Nur Klasse **REF**: die `neu`- und `geplant`-REF-Zeilen dieser Komponente aus `roadmap.py show`.
  Andere Klassen verweigern, mit Grund.
- Höchstens 15 Tasks, eine je Zeile; der Rest bleibt `neu` und wird am Gate genannt. Kopf wie in 3,
  `Spec: Roadmap R-a, R-b, …`; `Review: pro Task`, bei höchstens drei Tasks `am Ende`.
- Jede Task nennt ihre Roadmap-ID und trägt, was die Beweis-Konvention für ihre Klasse verlangt.

Beim Bündel gilt jeder Roadmap-Schritt des Gates für jede enthaltene Zeile.

## 4. Design-Gate — STOPP
- **Zeilenangaben frisch:** jede `datei:zeile` in Spec und Ledger unmittelbar vor dem Schreiben neu
  greppen.
- **Roadmap:** Hat das Vorhaben noch keine Zeile, trägt das Gate sie ein
  (`python3 scripts/dev/roadmap.py add --class <K> --title "…" --source "kevin <datum>" --ledger
  tasks/<slug>.md`) und setzt sie auf `geplant`; eine bestehende `neu`- oder `geplant`-Zeile wird
  `roadmap.py status R-nnnn geplant --ledger tasks/<slug>.md`. Beides nur für ein Vorhaben, das Kevin
  diktiert oder angenommen hat; ein eigener Fund bleibt `neu` bis zu Kevins Bestätigung. Nie ein Edit
  an der Datei.
- **Plan auf den Branch:** `git switch --no-track -c feature/<slug> origin/main`, Spec und Ledger
  stagen, `bash scripts/dev/ledger.sh lint tasks/<slug>.md` (Exit 1: beheben), `bash scripts/dev/review.sh
  sec --staged` (Exit 4: nicht committen, melden), dann committen
  (`chore(plan): add spec + ledger for <slug>`, ohne Spec `chore(plan): add ledger for <slug>`) und
  zurück mit `git switch main`.
- **Parallel-Tauglichkeit:** gegen jede `aktiv`- und `freigegeben`-Zeile (`roadmap.py show`) prüfen, ob
  das Vorhaben disjunkt ist — Komponenten und geteilte Contract-Dateien (API-Routen/Schemas,
  Migrationen, FRP-Config, Tauri-Commands, `run.sh`/`ci.yml`, primäre `docs/`-Seiten). Das Ledger
  einer anderen Zeile liegt auf ihrem Branch (`git show <branch>:tasks/<slug>.md`). Dazu muss
  `df -h /` Platz für den zweiten Worktree lassen (Desktop 4–6 GiB). Ergebnis je Zeile: „parallel-tauglich zu R-nnnn:
  ja/nein — <Grund>“; überlappt es, seriell empfehlen. Danach die nächste offene Roadmap-Zeile ebenso prüfen
  und, wenn sie passt, vorschlagen („parallel baubar: R-nnnn — <Grund>“), damit Kevin beide freigeben kann.
- Präsentieren: **1 Absatz** Zusammenfassung, die **Task-Liste** (Titel + Verify), **alle offenen
  Fragen** herausgestellt, und den Satz: „Freigabe: `! python3 scripts/dev/roadmap.py approve R-nnnn` (beim
  Bündel je Zeile); danach `/feature-build tasks/<slug>.md`.“
- **Die Freigabe ist Kevins** `roadmap.py approve` (CLAUDE.md §4); die Session setzt sie nie.
- **Implementiere nichts.** Kein Produktivcode, kein weiterer Branch, nichts auf `main`.
