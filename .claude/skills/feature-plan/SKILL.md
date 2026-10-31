---
name: feature-plan
description: Plane ein neues Feature/Change und zerlege es in eine Spec + eine Ledger aus fachlich zusammenhängenden, gemeinsam testbaren Tasks. Nutzen, wenn ein nicht-triviales Vorhaben startet ("ich will Feature X", "baue Y ein", "plane Z"), BEVOR Code entsteht. Endet an einem Design-Gate mit Bericht an Kevin; danach gibt die Session die Zeile selbst frei — implementiert selbst nichts. Mit --kurz R-nnnn ein Kurz-Ledger aus einer belegten Roadmap-Zeile, mit --zug tasks/<zug>.md alle Zeilen eines Zugs als ein Ledger.
---

# Feature planen & in autonome Tasks zerlegen

Diese Phase macht aus einer Idee zwei Artefakte: eine **Spec** und eine **Task-Ledger**
aus fachlich zusammenhängenden, je für sich verifizierbaren Aufgaben, die `/feature-build` ohne
Rückfragen abarbeiten kann. **Am Ende: Design-Gate — Bericht an Kevin, dann gibt die Session selbst frei (4).
In dieser Phase entsteht KEIN Produktivcode.** Spec und Ledger werden am Gate der erste
Commit auf dem Feature-Branch (R-0065).

**Drei Aufrufe:** `/feature-plan <idee>` — der volle Weg mit Spec (Abschnitte 1–4);
`/feature-plan --kurz R-nnnn` — ein Kurz-Ledger aus einer Roadmap-Zeile, ohne Spec (3a);
`/feature-plan --zug tasks/<zug>.md` — alle wartenden Zeilen eines Zugs (`roadmap.py zuege`) in
einem Ledger (3a). Alle drei enden am selben Design-Gate (4). Das Gate committet in dieses öffentliche
Repo, SEC-Funde bleiben unter `tasks/private/`: eine SEC-Zeile plant nur die Kern-Session, und nur
neutral — im vollen Weg oder in einem Zug mit neutralem Namen, nie mit `--kurz` (3a).

Modell: die Session plant selbst (CLAUDE.md §6) und liest Code und Doku direkt, ohne
Explorer-Sub-Agenten. Schwierige Architektur oder Sicherheitsfragen: gezielt `advisor` fragen (per Aufruf `xhigh`),
oder Kevin fährt die Planung mit `claude --effort xhigh` (CLAUDE.md §6). Vor dem Schreiben `.claude/rules/docs.md` und `.claude/rules/testing.md` lesen. Sprache: Deutsch,
Bezeichner im Original (CLAUDE.md).

## 0. Interaktiv arbeiten
Sobald eine echte Mehrdeutigkeit auftaucht, die die Spec verändert (Scope, gewünschtes
Verhalten, betroffene Komponente, Trade-off-Wahl), **frag sofort per `AskUserQuestion`**,
2–4 Fragen je Runde, Empfehlung als erste Option. Implementierungsdetails wählst du selbst;
alles, was das *Was* oder das sichtbare Verhalten betrifft, wird gefragt.

## 1. Verstehen & explorieren
- Kommt das Vorhaben aus der Roadmap (`R-nnnn`), zuerst die Zeile lesen:
  `python3 scripts/dev/roadmap.py show R-nnnn` (Quelle, Beweis, Abhängigkeiten, Dedup-Key).
- Scope und Erfolgskriterium klären; Produktentscheidungen nicht still treffen.
- Betroffene Komponenten lesen und **konkrete Dateien nennen**: Module, API-Routen, Pydantic-Schemas,
  DB-Tabellen, UI-Seiten, Rust-Commands, Go-Pakete.
- In `docs/` nachschlagen, wie sich Bestehendes verhält. Berührt das Vorhaben ein externes
  Wire-Protokoll (**FRP**, **Tauri**, **VictoriaMetrics**), die offizielle Doku per `WebFetch` lesen.

## 2. Spec schreiben → `docs/features/<slug>.md`
Slug = kurz, kebab-case. Abschnitte: **Problem / Motivation** · **Ziel & Nicht-Ziele** (YAGNI) ·
**Betroffene Komponenten & Dateien** · **Datenmodell / API / Migrationen** (Alembic? Vertrags-Drift
Server ↔ Web ↔ Desktop ↔ Agent?) · **Externe Integrationen** (mit Doku-Link) · **Trade-offs &
Alternativen** (mit Empfehlung) · **Risiken & Rollback** · **Doku-Impact** (1–2 Sätze, proportional:
die Seiten mit dokumentiertem Verhalten, API, Architektur, Konfiguration, Installation oder Betrieb, DE+EN;
internes Refactoring „keine“) · **Offene Fragen**.

## 3. Ledger schreiben → `tasks/<slug>.md`
Immer eine eigene Datei pro Vorhaben (Format: `tasks/README.md`). Kopf:

```
# <Feature> — Task-Ledger
Status: geplant · Branch: feature/<slug> · Review: pro Task
Spec: docs/features/<slug>.md (Roadmap R-nnnn)
Heavy: none — <warum keine schwere Suite>
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung
```
`Review: am Ende` für ein **Kurz-Ledger** mit ≤ 3 Tasks (ein Review über den Branch-Diff). Eine einzelne Task, die
nur Doku ändert (Markdown, HTML unter `docs/`), trägt `Task-Review: am Ende`: ihr Inhalt geht in die
Abschlussprüfung, `task-close.sh` verlangt dann kein Task-Urteil (und doch eines, sobald sie anderes stagt:
`.env.example`, Code unter `docs/`, einen Harness-Text, einen Symlink).
`Heavy:` aus „Betroffene Komponenten“ der Spec, nach ` — ` die Begründung: `none` (kein Stack-,
Gateway-, PKI- oder Install-Pfad); `linux-full` (Server-API/Gateway, `apps/ca-issuer`, `apps/agent`,
Desktop-Journeys, `docker-compose*.yml`); `scenario <flags>` (Cross-Host: FRP-Tunnel-Datenpfad,
:8444-Provisioning, `build-deb.sh`/`build-rpm.sh`, `scripts/install|update`, mTLS/PKI; nur die
passenden Flags, bleibt ask-first); `windows` (die Windows-VM).

**Task-Zuschnitt: zusammenhängend statt klein.**
- Eine Task ist eine fachlich zusammengehörige Änderung, die gemeinsam getestet wird und als ein Commit Sinn
  ergibt — etwa Route, Schema, Test und Client-Aufruf einer Funktion, nicht vier Mini-Tasks. Richtwert: eine
  Komponente (ein `Verify:`), bis etwa acht Dateien; mehr nur mit Begründung im Ledger.
- Getrennt wird, was unabhängige Risiken trägt (Migration, Auth/PKI, Wire-Format, Install) oder einzeln
  zurücknehmbar sein muss, und was Risikopfade (`scripts/dev/review-risk.txt`) mit Routinearbeit mischen würde.
- Jede Task hat ein **`Verify:`** in Flag-Form ohne Env-Präfix:
  `bash scripts/dev/verify.sh <komponente> --strict [-- <test>]`. Schwere Läufe stehen in `Heavy:`,
  nie in einer Task.
- Jede Task ist für sich testbar; Reihenfolge nur bei echter Abhängigkeit.
- Steckt in einer Task eine Design-Entscheidung, gehört sie als offene Frage in die Spec. Ist es eine Entscheidung
  aus Kevins Bereich (CLAUDE.md §2), die weder die Roadmap-Zeile noch sein Wort schon trifft, trägt die Task
  `[?] (<Frage>)` in der Überschrift (die Form von `ledger.sh mark-question`) und wird erst nach seiner Antwort
  gebaut.
- Neue Datei ⇒ die Task nennt den SPDX-Header. Neuer Flow ⇒ die Task enthält den Test.
- `Doku:` nach `.claude/rules/docs.md`: die Dateien, die die Task selbst nachzieht; oder `→ T<n>`, wenn eine
  Doku-Task am Ende des Ledgers die abgestimmten Abschnitte DE+EN gebündelt nachzieht; oder `keine (<Grund>)` bei
  Änderungen ohne dokumentierten Einfluss.
- `Komponente:` ist der Name aus `verify.sh` (`server`, `web`, `desktop-ui` …), kein Pfad: `task-close.sh`
  vergleicht ihn wörtlich mit den Komponenten des `Verify:`.

Task-Schema:
```
### T<n> — <Titel>  [ ]
Komponente: <komponente> · Dateien: …
Änderung: <was genau, 1–3 Sätze>
Verify: bash scripts/dev/verify.sh <komponente> --strict
Doku: <docs/… DE+EN · README · changelog.d/<slug>.md  |  → T<n>  |  keine (Grund)>
Task-Review: am Ende   (nur bei einer reinen Doku-Task)
Abhängt von: T<k>   (nur falls nötig)
Test-Löschung: <datei>::<test> — <Grund>   (nur falls nötig; ganze Datei: <datei>::*)
```
Löscht eine Task einen Test oder eine Testdatei, kündigt der Plan das an (`tasks/README.md`): die
Ankündigung zählt nur committet, und der Plan-Commit am Gate ist der Weg dorthin.

## 3a. Die kurzen Wege: `--kurz` und `--zug`

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

**`--zug tasks/<zug>.md`** — ein Zug (CLAUDE.md §2): die wartenden Zeilen, deren Spalte `Ledger` diesen Pfad nennt
(`roadmap.py zuege`), jede Klasse:
- Der Slug ist der des Zugs (`klein-doku-3` → `feature/klein-doku-3`); `klein-` plant nur die Klein-Session, alle
  anderen die Kern-Session (`--stufe`).
- **Überlappung zuerst:** `bash scripts/dev/overlap.sh --except feature/<slug> <Dateien der Zeilen>`. Ändert ein
  offener Branch dieselben Dateien, fährt die Zeile nicht mit: `roadmap.py status R-nnnn geplant --ledger
  tasks/<nächster-zug>.md --note "<bisherige Notiz>; überlappt feature/<x>"`.
- Eine Zeile je Task, zusammengehörige Zeilen (dieselben Dateien) in einer Task; höchstens 15 Tasks und eine
  schwere Prüfstufe. Was nicht passt, wandert in den nächsten Zug (wie oben) und wird am Gate genannt.
- Eine Zeile mit offener Frage aus Kevins Bereich fährt nicht mit (nächster Zug, die Frage am Gate); der Zug wartet
  nie auf eine einzelne Zeile.
- Kopf wie in 3, `Spec: docs/features/<slug>.md (Roadmap R-a, R-b, …)` mit einer kurzen Spec (Problem je Zeile,
  Doku-Impact, Risiken); `Review: pro Task`, bei höchstens drei Tasks `am Ende`; reine Doku-Tasks
  `Task-Review: am Ende` (3).
- Jede Task nennt ihre Roadmap-ID und trägt, was die Beweis-Konvention für ihre Klasse verlangt (BUG/REG:
  `Beweis:` und der Test, der den Fund zeigt).
- SEC-Zeilen fahren nur in einem Kern-Zug mit neutralem Namen (`kern-<bereich>-<n>`, nie `sec-`: Branch, Ledger und
  `changelog.d/<slug>.md` sind öffentlich, bevor der Fix released ist); Titel, Spec und CHANGELOG-Eintrag ohne
  Angriffspfad, Details nur in `tasks/private/`, `security` je Task.

**Mitnehmen** (voller Weg und `--kurz`): wartende `klein-`- oder Kern-Zeilen, die genau die Dateien dieses Vorhabens
ändern (`roadmap.py zuege`, ihre Quelle), nimmt das Vorhaben als eigene Tasks mit, höchstens drei, wenn sie keine
schwerere Prüfstufe und keinen anderen Merger brauchen; ihre Spalte `Ledger` wechselt auf dieses Ledger.

Bei Zug und Mitnehmen gilt jeder Roadmap-Schritt des Gates für jede enthaltene Zeile.

## 4. Design-Gate — STOPP
- **Zeilenangaben frisch:** jede `datei:zeile` in Spec und Ledger unmittelbar vor dem Schreiben neu
  greppen.
- **Roadmap:** Hat das Vorhaben noch keine Zeile, trägt das Gate sie ein
  (`python3 scripts/dev/roadmap.py add --class <K> --title "…" --source "kevin <datum>" --ledger
  tasks/<slug>.md`) und setzt sie auf `geplant`; eine bestehende `neu`- oder `geplant`-Zeile wird
  `roadmap.py status R-nnnn geplant --ledger tasks/<slug>.md`; trägt die Zeile eine Notiz, gibt das Gate sie
  wörtlich mit `--note` wieder mit (`status` ohne `--note` löscht sie). Beides nur für ein Vorhaben, das Kevin
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
  `df -h /` Platz für den zweiten Worktree lassen (Desktop 4–6 GiB). Ergebnis je Zeile: „parallel-tauglich zu
  R-nnnn: ja/nein — <Grund>“; überlappt es, seriell empfehlen. Danach einen Partner suchen:
  `python3 scripts/dev/roadmap.py next --status geplant --exclude-components <Komponenten dieses Ledgers>`, ohne
  Treffer dasselbe mit `--status neu` (SEC ausgenommen); Contract-Dateien und Platz selbst prüfen. Vorschlag:
  „parallel baubar: R-nnnn — <Grund>“ (`geplant` mit Plan auf seinem Branch: die Session gibt beide frei) oder
  „parallel planbar: R-nnnn“ (`neu`, erst planen).
- Präsentieren: **1 Absatz** Zusammenfassung, die **Task-Liste** (Titel + Verify), **alle offenen
  Fragen** herausgestellt, je mit Empfehlung und den `[?]`-Tasks, dazu jede `Test-Löschung:`.
- **Freigabe:** gleich nach dem Bericht gibt die Session frei, `python3 scripts/dev/roadmap.py approve R-nnnn`
  (beim Bündel je Zeile; die Notiz bleibt), wenn Kevin die Zeile angenommen oder das Vorhaben diktiert hat und
  nicht jede Task auf `[?]` steht; danach `/feature-build tasks/<slug>.md`. Nie für eine Zeile ohne committeten Plan
  (CLAUDE.md §4, §11).
- **Implementiere nichts.** Kein Produktivcode, kein weiterer Branch, nichts auf `main`.
