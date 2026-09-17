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
  Granularität, **Fast-Suite**, **Warm-Profil**, DoD-Verweis.
- **`Fast-Suite: crabbox`** (parallele Worktree-Lane, keine lokalen Toolchain-Artefakte —
  AUTONOMOUS.md „Parallel-Betrieb"): ALLE Verify-/Schnellsuite-Schritte laufen auf der
  warmen Lane-Box statt lokal. Einmalig `bash scripts/tests/crabbox_warm.sh <Warm-Profil>`
  (Default `desktop`; `pond` nur wenn im Kopf). Pro Task: das `Verify:` via
  `bash scripts/tests/crabbox_iter.sh --cmd '<befehl>'`, die Komponenten-Schnellsuite via
  `bash scripts/tests/crabbox_iter.sh quick --strict --only <komponenten>` (Keys: server
  monitoring ca-issuer agent desktop(-rs|-ui|-e2e) web scripts). Nichts lokal bauen/testen.
  Fehlt das Feld oder steht `lokal` → unverändert lokale Suiten (Solo-Default).
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
3. **Testen in zwei Ebenen: gezielt pro Task, voll vor dem Commit.** Befehle in Flag-Form,
   weil eine Allow-Regel nie über ein Env-Präfix matcht:
   - **Pro Task nur das `Verify:` des Eintrags, mit gezielten Args** —
     `bash scripts/dev/verify.sh <komponente> --strict -- <pfad/zum/test>` (z. B.
     `… server --strict -- tests/test_auth.py`). Die ganze Komponenten-Suite nach jeder
     einzelnen Task kostet Minuten und beweist nichts, was der Check vor dem Commit nicht
     auch beweist.
   - **Einmal unmittelbar vor dem Commit die volle Schnellsuite der berührten
     Komponente(n):** `bash scripts/dev/verify.sh <komponente> --strict` — fährt den
     **quick**-Layer dieser Komponente (Lint *und* Unit: ruff/gofmt/shellcheck plus die
     Suite), löst `.devenv.sh`/`AH_TEST_DB` selbst auf und schreibt `last-verify.json`.
     Mehrere Komponenten auf einmal: `bash scripts/tests/run.sh quick --strict --only <komp…>`.
     Keys: server monitoring ca-issuer agent desktop(-rs|-ui|-e2e) web scripts. Deren
     Summary-Zeile ist die Evidenz, die der Reviewer in Schritt 4 zitiert bekommt.
   - **Ein Lauf zur Zeit — nie zwei Testläufe gleichzeitig.** Die Server-Suite teilt sich
     **eine** Postgres-Test-DB (`AH_TEST_DB`), und die Alembic-Smoke legt pro Lauf eine
     Wegwerf-DB darin an: ein zweiter Lauf daneben ist **verworfen, nicht rot** — er beweist
     nichts und nimmt dem ersten seine Aussage. Einen Lauf starten, seine Summary abwarten,
     dann den nächsten.
   - **Lange Läufe nicht als Hintergrund-Bash**, sondern im tmux mit Wächter (CLAUDE.md § 2
     „Lange Läufe laufen überwacht"): ein Hintergrund-Task wird gekillt und puffert seine
     Ausgabe bis zum Ende, im tmux bleibt der Lauf sichtbar und überlebt.
   - `--strict` ist Pflicht: ohne das Flag zählt ein SKIP als Erfolg, und genau daran
     ist die alte Kette grün geworden, ohne dass etwas lief.
   - Bei `Fast-Suite: crabbox`: dieselben Checks remote über `crabbox_iter.sh` (s. „Vor
     dem Start"), nicht lokal.
   - **Grün** → Eintrag `[x]` (+ 1 Stichwort was geändert).
   - **Rot durch deine Änderung** → fixen; nicht in ~2 Versuchen lösbar →
     `git restore --source=HEAD --staged --worktree -- <datei>` (Änderung zurücknehmen),
     `[~] (verworfen: Test rot: <kurz>)`, weiter. Diese Rücknahme passiert **im**
     Builder-Tree — Verwerfen ist hier der Zweck. Eine *Revert-Probe* dagegen
     (einen fertigen Fix testweise entfernen, um den Test rot zu sehen) läuft nie
     hier, sondern in einem eigenen Worktree: sonst löscht sie ungestagte Arbeit
     an anderen Tasks.
   - **Rot strukturell / unabhängig von dir** → **STOPP**: im Ledger vermerken, Lauf beenden,
     berichten. Nicht auf rotem Fundament weiterbauen.
4. **Frischer-Kontext-Review** (vor dem Commit jeder Einheit): erst die berührten Dateien
   gezielt stagen (`git add -- <pfade>`, **kein** `git add -A`), damit ein echter Diff
   existiert. Dann einen **frischen Sub-Agent** starten (Agent-Tool, `general-purpose`,
   `model: sonnet`) mit einem Prompt, der ihm explizit mitgibt: (a) **lies zuerst
   `.claude/skills/feature-review/SKILL.md`** und prüfe streng gegen dessen 7 Kriterien (er
   lädt den Skill NICHT von selbst); (b) der zu prüfende Diff ist `git diff --staged`; (c) die
   Soll-Vorgabe ist die Task + die Spec/Report-Stelle (Pfad aus dem `Spec:`-Feld des
   Ledger-Kopfs); (d) **die Suiten sind bereits gelaufen** — er fährt sie NICHT nach, sondern
   prüft die im Auftrag zitierte Summary-Zeile gegen den Diff und macht höchstens gezielte
   Mutations-Proben (einen einzelnen Test lesen oder ausführen, um zu sehen, ob er ohne den
   Fix rot würde). Er sieht **nur** das — nicht deinen Bau-Verlauf.
   - **Modell:** `model: sonnet` ist der Default. `opus` **nur**, wenn der Diff einen
     **Risikopfad** berührt: PKI/mTLS, Auth/AuthZ, SSRF-Guards, DB-Migrationen (Alembic),
     Release-Workflows (`.github/workflows/release*`, `scripts/install.sh`/`update.sh`).
   - **Zeitbudget 10 Minuten.** Liegt nach ~10 Minuten kein Urteil vor: den Agent stoppen
     (`TaskStop`) und **einmal** einen frischen mit engerem Prompt starten (nur die geänderten
     Dateien und die Kriterien 1–4 nennen). Bleibt auch der ohne Urteil → selbst gegen dieselben
     Kriterien reviewen, committen und im Ledger kennzeichnen:
     `[x] (Review: selbst — Sub-Agent ohne Urteil)`.
   Urteil:
   - `approve` → weiter zum Commit.
   - `request_changes` mit `blocker`/`wichtig` → Punkte beheben, betroffene Schnelltests
     erneut, **einmal** re-reviewen. Danach gelöst → Commit; braucht Entscheidung → `[?]` in
     den Ledger (nicht raten). Max. 2 Runden, dann Commit des Sauberen oder STOPP.
   - `nit`-Punkte optional miterledigen, nie blockierend.
   (Review-Granularität = Commit-Granularität. Ein **Kurz-Ledger** (≤ 3 Tasks) trägt im Kopf
   `Review: am Ende` — dann entfällt dieser Schritt pro Task und es gibt genau **einen**
   Gesamt-Review im Abschluss.)
5. **Committen** nach Granularität: *pro Task* → nach jeder grünen, reviewten Task ein
   `feat|fix|refactor(...): …`; *pro Komponente* → wenn alle Einträge **einer Komponente**
   innerhalb des Abschnitts grün+reviewt sind (Default für Report-Backlogs — hält Commits/
   Reviews klein); *pro Abschnitt* → wenn ein ganzer `##`-Abschnitt komplett und grün+reviewt
   ist. **Nie einen roten oder ungereviewten Stand committen.** Commit-Body: Task-IDs + Stichwort.

## Abschluss (kein `[ ]` mehr offen)
1. Gesamt-Schnellcheck: `bash scripts/tests/run.sh quick` (lint + unit); bei
   `Fast-Suite: crabbox` stattdessen `bash scripts/tests/crabbox_iter.sh quick` (ohne `AH_ONLY`).
2. **Schwere Suite auf crabbox — nur wenn nötig (path-gated, CLAUDE.md).** Erst den Branch-Diff
   prüfen (`git diff --stat main...`): Berührt er **heavy-relevante** Pfade? (`apps/server`-API/
   Gateway, `apps/ca-issuer`, `apps/gateway`, `apps/agent`, `apps/desktop` Connect/Tunnel/
   Enrollment, `docker-compose*.yml`, `Dockerfile`, `scripts/install|update`, FRP/PKI). **Wenn
   nein** (z. B. reine `docs/`-, Web-UI- oder Kleinkram-Änderung) → schwere Suite **überspringen**
   mit begründetem Vermerk, direkt zu Schritt 3. **Wenn ja:** dem `/test`-Skill folgen — Box warm
   → `run.sh quick` → `AH_ALLOW_REAL=1 run.sh integration` (+ `e2e` nur bei berührter
   `apps/web`/`apps/desktop`-Journey). Dabei das **`Warm-Profil` am realen Diff re-checken**,
   in beide Richtungen: `pond` geplant, aber keine Desktop-Journey im Diff → Single-Box
   reicht (zweite Box sparen); steht **`Abschluss: multibox …`** im Kopf ODER berührt der
   Diff Cross-Host-Pfade (FRP-Tunnel-Datenpfad, :8444-Provisioning, `build-deb/rpm`,
   `scripts/install|update`, mTLS/PKI) → den Multibox-Lauf **beim Nutzer anfragen**
   (ask-first — `crabbox_multibox.sh` bleibt bewusst prompt-pflichtig) und das Ergebnis in
   den PR-Body aufnehmen. Danach **`crabbox list`** prüfen (keine geleakten Leases)
   und `crabbox stop`/reap. **Nur bei realem Pass weiter — SKIP ≠ grün.** (Nutzt VM-Leases, die
   per `-ttl`/`-idle-timeout` self-reapen — nur der single-box-Warm-Loop, kein `multibox`/`bake`
   ohne Nachfrage.)
3. **Review über den Branch-Diff** — welcher, sagt das `Review:`-Feld des Kopfs:
   - **`Review: am Ende`** (Kurz-Ledger, ≤ 3 Tasks): **ein** Frischer-Kontext-Review über den
     ganzen Branch-Diff (`git diff main...`, Sub-Agent wie in Schritt 4) — und **kein**
     `/code-review` hinterher: der eine Reviewer hat genau diesen Diff schon gesehen, der
     zweite Durchgang kostet nur Zeit.
   - **`Review: pro Task`** (Default für große Ledger): die Einheiten sind einzeln reviewt,
     aber niemand hat das Ganze gesehen → hier `/code-review` über den Branch-Diff.
   Echte neue Bugs als Tasks in den Ledger, fixen, erneut testen.
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
