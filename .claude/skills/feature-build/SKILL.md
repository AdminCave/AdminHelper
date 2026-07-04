---
name: feature-build
description: Arbeite ein Task-Ledger aus tasks/ autonom ab (tasks/<slug>.md aus /feature-plan ODER tasks/audit-fixes.md aus einem Fable-Report) — jede kleine Task surgical umsetzen, schnelle Tests, frischer Review, pro Task auf einem Feature-Branch committen, am Ende die schwere crabbox-Suite fahren und einen Draft-PR öffnen. Nutzen nach freigegebenem Design-Gate oder zum Abarbeiten eines Fix-Backlogs. Läuft auf Opus.
---

# Feature / Backlog autonom bauen

Führt eine Task-Ledger **ohne weitere Rückfragen** aus (das Design-Gate war die
menschliche Freigabe) — bis zum Draft-PR. Modell: Opus. **Loop-tauglich:** großen
Backlog unter `/loop` starten; für ein normales Feature reicht eine Session.

Eingabe: der Ledger-Pfad unter `tasks/` (z. B. `tasks/<slug>.md`, `tasks/audit-fixes.md`).
Fehlt er, das **einzige** `Status: aktiv`-Ledger nehmen. Gibt es **mehrere** `aktiv` (oder
keins): **nicht interaktiv fragen** — im Loop wartet niemand — sondern mit klarer Meldung
abbrechen und den expliziten Pfad verlangen. `geplant`/`blockiert`/`erledigt` werden ohne Pfad
nie automatisch gebaut.

## Vor dem Start
- Ledger-Kopf lesen: **Status**, **Branch**, **Spec**, **Commit-Granularität**, **Review**-
  Granularität, DoD-Verweis.
- **Status prüfen:** `geplant` → das Starten von `feature-build` IST die Freigabe: Kopf auf
  `aktiv` setzen und bauen. `aktiv` → bauen. `blockiert`/`erledigt` → **nicht** bauen, melden.
- **Branch prüfen:** Ist `Branch:` der Default-Branch (`main`)? → **abbrechen** und melden
  („dieses Ledger ist Handarbeit auf `main`, nicht für feature-build"); der Flow braucht einen
  isolierten Branch für Recovery + Draft-PR. Sonst existenz-tolerant sicherstellen:
  `git switch <branch> 2>/dev/null || git switch -c <branch> main` (immer von `main` forken,
  nie vom aktuellen HEAD).
- **Der Ledger ist die einzige Wahrheit über den Fortschritt.** Zu Beginn jeder
  Iteration lesen, laufend aktualisieren.

## Pro Iteration (nächste ~1–8 offene Einträge, in Ledger-Reihenfolge)
1. Eintrag lesen; die zugehörige Stelle in Spec/Report + **echten Code + Kontext**
   (Aufrufer, Tests, Config) lesen. Zeilennummern können durch frühere Tasks verschoben
   sein → an **Symbol/Titel** orientieren, nicht blind an der Zeile.
2. Ehrlich entscheiden:
   - **Umsetzbar** → **surgical** implementieren, im Stil des umgebenden Codes, nur was
     der Eintrag verlangt (keine Drive-by-Refactors). Neuer Flow ⇒ Test dazu. Neue Datei
     ⇒ SPDX-Header (`reuse annotate --copyright "Kevin Stenzel" --license GPL-3.0-or-later`).
   - **Doku mit Augenmaß:** Bringt die Änderung eine **nennenswerte** nach außen sichtbare
     Wirkung (Feature, API/Endpunkt, CLI-Flag, Env-Var, Port, Config-/Wire-Format, Betriebs-/
     Install-Schritt, Architektur), gehört die passende Doku **in denselben Commit** (`docs/`
     DE+EN, ggf. `README.md`/`CHANGELOG.md`). **Bugfixes, Kleinkram und internes Refactoring
     brauchen keine Doku — nicht künstlich erzeugen.** Das `Doku:`-Feld der Task ist die
     Vorgabe; weicht die Realität ab, kurz begründen.
   - **Schon erledigt / hinfällig / Falsch-Positiv** → Code NICHT anfassen, `[~]` + ein Satz.
   - **Braucht Entscheidung / destruktiv / mehrdeutig** → NICHT raten, `[?]` + kurze Frage,
     überspringen (das ist ein legitimes Ergebnis, kein Versagen).
3. Erst das `Verify:` des Eintrags ausführen, dann die **schnelle Suite der berührten
   Komponente(n)** — nur was real existiert:
   - `apps/server`, `apps/monitoring`, `apps/ca-issuer`: `pytest -q` · `ruff check` · `ruff format --check`
   - `apps/agent`: `gofmt -l .` · `go vet ./...` · `go test ./...`
   - `apps/desktop/src-tauri`: `cargo fmt --check` · `cargo clippy -- -D warnings` · `cargo test`
   - `apps/desktop/ui`: `npm run check` · `npm run lint` · `npm run test`
   - `apps/web`: `npm run check` · `npm run lint` · `npm run test:unit`  (NICHT `test:e2e` — schwer)
   - **Grün** → Eintrag `[x]` (+ 1 Stichwort was geändert).
   - **Rot durch deine Änderung** → fixen; nicht in ~2 Versuchen lösbar → `git checkout -- <datei>`
     (Änderung zurücknehmen), `[~] (verworfen: Test rot: <kurz>)`, weiter.
   - **Rot strukturell / unabhängig von dir** → **STOPP**: im Ledger vermerken, Lauf beenden,
     berichten. Nicht auf rotem Fundament weiterbauen.
4. **Frischer-Kontext-Review** (vor dem Commit jeder Einheit): erst die berührten Dateien
   gezielt stagen (`git add -- <pfade>`, **kein** `git add -A`), damit ein echter Diff
   existiert. Dann einen **frischen Sub-Agent** starten (Agent-Tool, `general-purpose`) mit
   einem Prompt, der ihm explizit mitgibt: (a) **lies zuerst `.claude/skills/feature-review/
   SKILL.md`** und prüfe streng gegen dessen 7 Kriterien (er lädt den Skill NICHT von selbst);
   (b) der zu prüfende Diff ist `git diff --staged`; (c) die Soll-Vorgabe ist die Task +
   die Spec/Report-Stelle (Pfad aus dem `Spec:`-Feld des Ledger-Kopfs bzw. `../fabelreport.md`).
   Er sieht **nur** das — nicht deinen Bau-Verlauf. Urteil:
   - `approve` → weiter zum Commit.
   - `request_changes` mit `blocker`/`wichtig` → Punkte beheben, betroffene Schnelltests
     erneut, **einmal** re-reviewen. Danach gelöst → Commit; braucht Entscheidung → `[?]` in
     den Ledger (nicht raten). Max. 2 Runden, dann Commit des Sauberen oder STOPP.
   - `nit`-Punkte optional miterledigen, nie blockierend.
   (Review-Granularität = Commit-Granularität. Bei Kostendruck kann der Ledger-Kopf
   `Review: am Ende` setzen — dann nur ein Gesamt-Review in Schritt „Abschluss".)
5. **Committen** nach Granularität: *pro Task* → nach jeder grünen, reviewten Task ein
   `feat|fix|refactor(...): …`; *pro Komponente* → wenn alle Einträge **einer Komponente**
   innerhalb des Abschnitts grün+reviewt sind (Default für Report-Backlogs — hält Commits/
   Reviews klein); *pro Abschnitt* → wenn ein ganzer `##`-Abschnitt komplett und grün+reviewt
   ist. **Nie einen roten oder ungereviewten Stand committen.** Commit-Body: Task-IDs + Stichwort.

## Abschluss (kein `[ ]` mehr offen)
1. Gesamt-Schnellcheck: `bash scripts/tests/run.sh quick` (lint + unit).
2. **Schwere Suite auf crabbox — nur wenn nötig (path-gated, CLAUDE.md).** Erst den Branch-Diff
   prüfen (`git diff --stat main...`): Berührt er **heavy-relevante** Pfade? (`apps/server`-API/
   Gateway, `apps/ca-issuer`, `apps/gateway`, `apps/agent`, `apps/desktop` Connect/Tunnel/
   Enrollment, `docker-compose*.yml`, `Dockerfile`, `scripts/install|update`, FRP/PKI). **Wenn
   nein** (z. B. reine `docs/`-, Web-UI- oder Kleinkram-Änderung) → schwere Suite **überspringen**
   mit begründetem Vermerk, direkt zu Schritt 3. **Wenn ja:** dem `/test`-Skill folgen — Box warm
   → `run.sh quick` → `AH_ALLOW_REAL=1 run.sh integration` (+ `e2e` nur bei berührter
   `apps/web`/`apps/desktop`-Journey). Danach **`crabbox list`** prüfen (keine geleakten Leases)
   und `crabbox stop`/reap. **Nur bei realem Pass weiter — SKIP ≠ grün.** (Nutzt VM-Leases, die
   per `-ttl`/`-idle-timeout` self-reapen — nur der single-box-Warm-Loop, kein `multibox`/`bake`
   ohne Nachfrage.)
3. `/code-review` über den Branch-Diff. Echte neue Bugs als Tasks in den Ledger, fixen,
   erneut testen.
4. **Push + Draft-PR** (der eine bewusst prompt-pflichtige Schritt — nach außen wirkend):
   `git push -u origin <branch>`, dann `gh pr create --draft --title "<type>: <feature>"
   --body "…"` mit Link auf die **Spec** (Pfad aus dem `Spec:`-Ledgerfeld), Task-Zusammenfassung
   (fertig / übersprungen / offene `[?]`) und crabbox-Ergebnis. (Beide prompten, solange nicht
   allowlisted — das ist Absicht.)
5. Ledger-Kopf auf `Status: erledigt` setzen (bzw. `blockiert`, wenn `[?]`-Punkte offen
   bleiben). Schluss-Zusammenfassung im Chat; die `[?]`-Punkte klar auflisten — die
   entscheidet der Mensch.

## Recovery
- Granulare Commits ⇒ ein Fehlgriff = `git revert <commit>`, keine Handarbeit.
- Der Loop begräbt nie einen roten Stand: **grün + committen**, ODER **zurücknehmen + `[~]`**,
  ODER **STOPP**. Kein vierter Weg.

## Feste Regeln
- Während des Loops **nur schnelle Suiten**. Schwere crabbox-Suite **nur im Abschluss**.
  **Nie** `run.sh integration|e2e|all` mitten im Loop, nie `prewarm/job/checkpoint/image/bake`
  ohne Nachfrage (CLAUDE.md).
- Ehrlichkeit vor Fortschritt: nichts als `[x]`, dessen Suite nicht real grün lief.
- Surgical & zurückführbar: jede geänderte Zeile führt auf einen Ledger-Eintrag zurück.
- CLAUDE.md gilt vollständig (Sprache, Conventional Commits, SPDX, Doku-Pflege, DoD).
