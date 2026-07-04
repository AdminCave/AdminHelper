---
name: feature-review
description: Frischer-Kontext-Reviewer für einen Task-/Commit-Diff — prüft Auftragstreue, Korrektheit, Tests, Sicherheit, Stil, Doku und Regressions-Radius gegen feste Kriterien und gibt ein Urteil (approve / request_changes mit konkreten Punkten). Wird von feature-build automatisch pro Commit-Einheit aufgerufen; standalone nutzbar (auch unter /loop) zum Nachprüfen eines Branch-Diffs.
---

# Frischer Reviewer für einen Diff

Zweck: eine **zweite, unvoreingenommene Instanz** prüft den Code, den ein anderer Kontext
geschrieben hat. Der Wert liegt genau im **frischen Kontext** — der Reviewer kennt die
Implementierungs-Ausreden nicht und sieht nur das Ergebnis. Läuft auf Opus.

**Wichtig:** Diesen Review IMMER in frischem Kontext fahren — als eigenständigen Aufruf,
unter `/loop`, oder (aus `feature-build` heraus) als **frischer Sub-Agent** (Agent-Tool,
`general-purpose`), der nur Diff + Task + diese Kriterien sieht, nicht den Bau-Verlauf.

## Eingabe
- Der zu prüfende **Diff** (`git diff` gegen den Merge-Base von `main`, oder der staged Diff
  einer Commit-Einheit) plus die zugehörige **Task/Spec** (`tasks/<slug>.md`-Eintrag bzw.
  `fabelreport.md`-Fund) als Soll-Vorgabe.

## Prüf-Kriterien (jede Änderung gegen ALLE durchgehen)
1. **Auftragstreue.** Setzt der Diff **genau** die Task um — nicht weniger (fehlende Teile
   des `Verify:`-Ziels), nicht mehr (Scope-Creep, Drive-by-Refactors, unbeauftragte
   Formatierung)? Lässt sich jede geänderte Zeile auf die Task zurückführen?
2. **Korrektheit.** Edge-Cases (None/null/leer/0/Grenzwerte), Fehlerpfade, Off-by-one,
   Nebenläufigkeit/Races, Ressourcen-Leaks (offene Files/Connections/Tasks). Tut es unter
   realistischen **und** bösartigen Eingaben das Richtige?
3. **Tests.** Neuer Flow/Logik ⇒ gibt es einen Test? Prüft er **echtes Verhalten mit echten
   Assertions** (kein Scheintest, der nur „läuft durch")? Ist der **Fehlerpfad** abgedeckt,
   nicht nur der Happy Path? Würde der Test ohne den Fix rot?
4. **Sicherheit (projektkritisch).** Keine neue Injection (SQL/Command/TOML/Path/Template),
   keine AuthZ-Lücke (fehlender Permission-Check, IDOR), keine Secrets in Logs/Fehlern, keine
   deaktivierte TLS-Verifikation, Boundary-Validierung an neuen Eingängen vorhanden. Bei
   Zeitvergleichen von Secrets: constant-time?
5. **Stil & Konsistenz.** Passt es zum umgebenden Code (Naming, Muster, Fehlerbehandlung)?
   Keine durch die Änderung entstandenen toten Imports/Variablen/Funktionen?
6. **Doku & Konventionen (mit Augenmaß).** Bringt die Änderung eine **nennenswerte** nach
   außen sichtbare Wirkung (Feature, API/Endpunkt, CLI-Flag, Env-Var, Port, Config-/Wire-Format,
   Betriebs-/Install-Schritt, Architektur) und fehlt die passende Doku im selben Commit (`docs/`
   DE+EN)? → `request_changes`, Schwere **nach Bedeutung**: fehlende Doku zu einem echten
   Feature/Breaking-Change = `blocker`; zu Kleinerem = `wichtig`/`nit`. **Bugfixes, internes
   Refactoring und Kleinkram brauchen keine Doku — nicht einfordern** (sonst wärst du der
   Bürokrat, den CLAUDE.md mit YAGNI verbietet). Zusätzlich prüfen: SPDX-Header bei neuen
   Dateien, Commit-Message Conventional-Commit-tauglich (auf Englisch).
7. **Regression / Blast-Radius + synchron-zu-haltende Stellen.** Berührt der Diff einen
   **geteilten Contract** (API-Route, Pydantic-Schema, FRP-Config-Format, DB-Migration,
   Tauri-Command-Signatur), von dem andere Komponenten (Web/Desktop/Agent) abhängen?
   Rückwärtskompatibel? Migration reversibel? **Und die CLAUDE.md-Stolperfallen — hier gilt
   die Surgical-Regel NICHT:** Ändert der Diff nur **eine** von mehreren gekoppelten Stellen?
   Konkret als `blocker` melden, wenn eine berührt, aber die Partnerstelle nicht mitgezogen ist:
   `MINISIGN_PUBKEY` in `scripts/install.sh` **und** `scripts/update.sh` (müssen gleich sein);
   das Versions-Pin-Trio `tauri.conf.json` ↔ Agent-Tag/`build-deb.sh`/`build-rpm.sh` ↔
   `FRP_VERSION` in `.github/workflows/` (+ `crabbox_bootstrap.sh`).

## Urteil
Gib strukturiert zurück:
- **verdict**: `approve` | `request_changes`
- Bei `request_changes`: eine Liste **konkreter, umsetzbarer** Punkte — je mit
  `schwere` (blocker | wichtig | nit), `datei:zeile` und **was genau** zu ändern ist.
- **Ehrlichkeit vor Gründlichkeit:** Ein frischer Reviewer sucht keine Alibi-Nits, um sich
  zu rechtfertigen. Ist nichts Konkretes falsch → `approve`. `nit`-Punkte blockieren nie.

## Verwendung durch feature-build
- Nach grünen Schnelltests, **vor** dem Commit einer Einheit: Reviewer (frischer Kontext)
  laufen lassen.
- `approve` → committen.
- `request_changes` mit `blocker`/`wichtig` → Punkte beheben, betroffene Schnelltests erneut,
  **einmal** re-reviewen; danach: gelöst → committen; braucht Entscheidung → `[?]` in den
  Ledger, nicht raten. Max. 2 Review-Runden pro Einheit, dann committen oder STOPP.
- `nit`-Punkte optional gleich miterledigen, aber nie blockierend.
