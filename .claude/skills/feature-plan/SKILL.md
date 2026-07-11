---
name: feature-plan
description: Plane ein neues Feature/Change und zerlege es in eine Spec + eine Ledger aus kleinen, autonom abarbeitbaren Tasks. Nutzen, wenn ein nicht-triviales Vorhaben startet ("ich will Feature X", "baue Y ein", "plane Z"), BEVOR Code entsteht. Endet an einem Design-Gate zur menschlichen Freigabe — implementiert selbst nichts.
---

# Feature planen & in autonome Tasks zerlegen

Diese Phase macht aus einer Idee zwei Artefakte: eine **Spec** und eine **Task-Ledger**
aus so kleinen, unabhängig verifizierbaren Aufgaben, dass die Build-Phase sie ohne
Rückfragen abarbeiten kann. **Am Ende: Design-Gate — stoppen, auf Freigabe warten.
In dieser Phase entsteht KEIN Produktivcode und KEIN Branch.**

Modell: Opus (wie alles hier). Sprache: Deutsch, Bezeichner im Original (CLAUDE.md).

## 0. Interaktiv arbeiten (diese Phase ist ein Dialog, kein Alleingang)
Planen ist **interaktiv**. Sobald eine echte Mehrdeutigkeit auftaucht, die die Spec
verändert (Scope, gewünschtes Verhalten, betroffene Komponente, Trade-off-Wahl), **frag
sofort per `AskUserQuestion`** — nicht still entscheiden, nicht nur ans Gate schieben. Eine
falsche Annahme früh kostet die ganze Spec. Faustregel: Implementierungsdetails darfst du
selbst wählen; alles, was das *Was* oder das sichtbare Verhalten betrifft, wird gefragt.
Bündle 2–4 Fragen pro Runde, mit einer Empfehlung als erster Option.

## 1. Verstehen & explorieren
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
Spec: docs/features/<slug>.md
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung
```
(`Spec:` = Rück-Link zur Soll-Vorgabe, die `feature-build`/`feature-review` als Referenz
nutzen — bei einem Report-Backlog stattdessen z. B. `Spec: ../fabelreport.md`.)
(`Status:` = Ledger-Zustand `geplant|aktiv|erledigt|blockiert`. `feature-plan` schreibt
`geplant` — die menschliche Freigabe bzw. der Start von `/feature-build` macht daraus `aktiv`.
Nicht mit dem Task-Status `[ ]`/`[x]` verwechseln.)

**Task-Größe = autonomietauglich** (die wichtigste Regel dieser Phase):
- Eine Task ≈ **eine fokussierte Änderung**, möglichst **eine Komponente**, ≤ ~3 Dateien.
- Jede Task hat ein **`Verify:`** — ein konkreter Befehl/Assertion, der grün/rot sagt
  (Unit-Test, Route-Call, `svelte-check`, `go test`). Kein „sieht gut aus".
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
Verify: <konkreter Befehl / Assertion>
Doku: <docs/… DE+EN · README · CHANGELOG  |  keine (intern)>
Abhängt von: T<k>   (nur falls nötig)
```

## 4. Design-Gate — STOPP
- Präsentiere im Chat: **1 Absatz** Zusammenfassung, die **Task-Liste** (Titel + Verify),
  und **alle offenen Fragen** klar herausgestellt.
- Sage explizit: „Bitte `docs/features/<slug>.md` und `tasks/<slug>.md` prüfen/anpassen.
  Zum autonomen Bauen: **`/feature-build tasks/<slug>.md`** in einer Opus-Session."
- **Implementiere nichts, lege keinen Branch an.** Diese Phase endet hier.
