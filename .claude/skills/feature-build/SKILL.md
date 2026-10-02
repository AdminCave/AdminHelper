---
name: feature-build
description: Arbeite ein Task-Ledger aus tasks/ autonom ab (tasks/<slug>.md aus /feature-plan ODER tasks/audit-fixes.md aus einem Fable-Report) — jede kleine Task surgical umsetzen, schnelle Tests, frischer Review, pro Task auf einem Feature-Branch committen, am Ende die schwere VM-Suite fahren und einen Draft-PR öffnen. Nutzen nach freigegebenem Design-Gate oder zum Abarbeiten eines Fix-Backlogs. Läuft auf Opus.
---

# Feature / Backlog autonom bauen

Führt eine Task-Ledger **ohne weitere Rückfragen** aus (das Design-Gate war die
menschliche Freigabe) — bis zum Draft-PR. Modell: Opus. **Loop-tauglich:** großen
Backlog unter `/loop` starten; für ein normales Feature reicht eine Session.

Eingabe: der Ledger-Pfad unter `tasks/` (z. B. `tasks/<slug>.md`, `tasks/audit-fixes.md`).
Fehlt er, das **einzige** `Status: aktiv`-Ledger nehmen. Gibt es **mehrere** `aktiv` (oder
keins): **nicht interaktiv fragen** — im Loop wartet niemand — sondern mit klarer Meldung
abbrechen und den expliziten Pfad verlangen. `geplant`, `freigegeben`, `bereit`, `blockiert`
und `erledigt` werden ohne Pfad nie automatisch gebaut (den Worker für `freigegeben` bringt
Stufe 7).

## Vor dem Start
- **Plan finden:** Seit R-0065 liegt ein geplantes Ledger bis zum Merge nur auf seinem Branch
  (der erste Commit von `feature/<slug>`). Steht `tasks/<slug>.md` nicht im Arbeitsbaum,
  zuerst dorthin wechseln: `git switch feature/<slug>` (den Branch legt `feature-plan` am Gate
  an, `git branch --list 'feature/*'` zeigt ihn; in einer Lane ist man schon dort). Ohne Pfad
  sucht der Bau nur im Arbeitsbaum.
- Ledger-Kopf lesen: **Status**, **Branch**, **Spec**, **Commit-Granularität**, **Review**-
  Granularität, **Heavy** (bei älteren Ledgern ohne `Heavy:` stattdessen **Fast-Suite** und
  **Warm-Profil**), DoD-Verweis.
- **`Fast-Suite: vm`** (nur ältere Ledger; parallele Worktree-Lane, keine lokalen Toolchain-Artefakte —
  AUTONOMOUS.md „Parallel-Betrieb"): ALLE Verify-/Schnellsuite-Schritte laufen auf der
  warmen Lane-Box statt lokal. Einmalig `bash scripts/vm/warm.sh <Warm-Profil>`
  (Default `desktop`; `pond` nur wenn im Kopf). Pro Task: das `Verify:` via
  `bash scripts/vm/iter.sh --cmd '<befehl>'`, die Komponenten-Schnellsuite via
  `bash scripts/vm/iter.sh quick --strict --only <komponenten>` (Keys: server
  monitoring ca-issuer agent desktop(-rs|-ui|-e2e) web scripts). Nichts lokal bauen/testen.
  Fehlt das Feld oder steht `lokal` → unverändert lokale Suiten (Solo-Default).
- **Status prüfen** (Folge `geplant` → `freigegeben` → `aktiv` → `bereit` → `erledigt`,
  tasks/README.md): `freigegeben` → Kevins Freigabe liegt vor: Kopf auf `aktiv` setzen und
  bauen. `geplant` → nur mit ausdrücklichem Pfad; dann IST das Starten die Freigabe: Kopf auf
  `aktiv`. `aktiv` → weiterbauen. `bereit` → alle Tasks sind zu: **keine** Task bauen. Gibt es
  für den Branch schon einen PR (`gh pr view <branch>`, etwa von Kevin geöffnet), fehlen nur Kopf
  und Roadmap aus Abschluss-Schritt 5 und 6: den Kopf auf `erledigt` (bzw. `blockiert`)
  committen — der Commit muss noch in den PR, pushen tut Kevin —, die Roadmap wie unter
  „Roadmap mitziehen" (`pr --pr`, ein Teil-Ledger `aktiv --pr`; eine Zeile, die noch auf `aktiv`
  steht, zuerst auf `bereit`), dann melden; sonst war der Abschluss unterbrochen (etwa von einem
  Compact) und geht ab Schritt 1 weiter — den Kopf setzt schon `task-close.sh`, die Roadmap-Zeile
  vielleicht noch nicht, und Schritt 1 ist wiederholbar. `erledigt` →
  **nicht** bauen; gibt es einen PR und steht die Roadmap-Zeile noch auf `bereit` (beim
  Teil-Ledger: seine Nummer fehlt in der Spalte `PR`), Schritt 6 nachholen, dann melden; gibt es
  keinen PR, melden: Push und PR stehen aus, das ist Kevins Handgriff. `blockiert` → **nicht**
  bauen, melden.
- **Roadmap mitziehen:** Nennt der Ledger-Kopf Roadmap-IDs — im `Spec:` (`Roadmap R-nnnn`,
  `docs/features/<slug>.md (Roadmap R-nnnn)`, beim Bündel `Roadmap R-a, R-b, …`) oder in der
  Zeile `Roadmap: R-nnnn` der Regressions-Ledger aus `heavy.sh` —, folgt jede
  dieser Zeilen dem Ledger, nur über `python3 scripts/dev/roadmap.py status R-nnnn <status>`, je
  ID ein Aufruf: beim Start `aktiv`, im Abschluss `bereit`, mit dem PR `pr --pr "#<n>"` (die
  Spalte `PR`, die `sync` liest); `abgeschlossen` setzt nach dem Merge `roadmap.py sync`. Steht
  eine Zeile beim Start noch auf `neu` oder `geplant` (etwa die eines Regressions-Ledgers aus
  `heavy.sh`, die `neu` ist), geht das nur bei ausdrücklichem Start — der Pfad ist wie bei
  `geplant` Kevins Freigabe — und nur über die erlaubte Kette, je Schritt ein Aufruf mit
  Exit-Prüfung: `status R-nnnn geplant` (nur von `neu`), `approve R-nnnn`, `status R-nnnn
  aktiv`; ohne ausdrücklichen Start: melden. Ist das Ledger nur ein Teil der Zeile (`Roadmap R-nnnn, Teil …`), bleibt sie mit dem PR `aktiv` und
  sammelt nur die Nummern: `status R-nnnn aktiv --pr "#<n>"`, ab dem zweiten Teil
  `--pr "#<a>, #<n>"` — `sync` schließt nur eine Zeile in `pr`, und die setzt erst der letzte
  Teil. Nie ein Edit an der Datei. Ein Exit ≠ 0 wird gemeldet, nicht umgangen (Exit 5: die
  Datei ist gerade von Hand offen — Kevin fragen).
- **Branch prüfen:** Ist `Branch:` der Default-Branch (`main`)? → **abbrechen** und melden
  („dieses Ledger ist Handarbeit auf `main`, nicht für feature-build"); der Flow braucht einen
  isolierten Branch für Recovery + Draft-PR. Sonst existenz-tolerant sicherstellen:
  `git switch <branch> 2>/dev/null || git switch -c <branch> main` (immer von `main` forken,
  nie vom aktuellen HEAD).
- **Der Ledger ist die einzige Wahrheit über den Fortschritt.** Zu Beginn jeder
  Iteration lesen, laufend aktualisieren.

## Pro Iteration (nächste ~1–8 offene Einträge, in Ledger-Reihenfolge)
0. **Task anmelden:** `bash scripts/dev/ledger.sh start <ledger> <id>` — schreibt Ledger, ID,
   Komponente und `Dateien:` nach `.vm/active-task` (Anzeige und Preflight). Geprüft wird
   später die `Dateien:`-Zeile **der Task im Ledger**: braucht die Task eine Datei, die nicht
   drinsteht, wird die Liste sichtbar erweitert (`ledger.sh set-files`), nicht der Scope
   gelockert.
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
   - **Schon erledigt / hinfällig / Falsch-Positiv** → Code NICHT anfassen,
     `bash scripts/dev/ledger.sh mark-skip <ledger> <id> "<ein Satz>"`.
   - **Braucht Entscheidung / destruktiv / mehrdeutig** → NICHT raten:
     `bash scripts/dev/ledger.sh mark-question <ledger> <id> "<frage>"`, überspringen
     (das ist ein legitimes Ergebnis, kein Versagen).
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
   - Bei `Fast-Suite: vm`: dieselben Checks remote über `scripts/vm/iter.sh` (s. „Vor
     dem Start"), nicht lokal.
   - **Grün** → weiter zum Review. Den Haken setzt **nicht mehr die Session**, sondern
     `task-close.sh` in Schritt 5 — zusammen mit der Summary-Zeile, die ihn trägt.
   - **Rot durch deine Änderung** → fixen; nicht in ~2 Versuchen lösbar →
     `git restore --source=HEAD --staged --worktree -- <datei>` (Änderung zurücknehmen),
     `ledger.sh mark-skip <ledger> <id> "verworfen: Test rot: <kurz>"`, weiter. Diese Rücknahme passiert **im**
     Builder-Tree — Verwerfen ist hier der Zweck. Eine *Revert-Probe* dagegen
     (einen fertigen Fix testweise entfernen, um den Test rot zu sehen) läuft nie
     hier, sondern in einem eigenen Worktree: sonst löscht sie ungestagte Arbeit
     an anderen Tasks.
   - **Rot strukturell / unabhängig von dir** → **STOPP**: im Ledger vermerken, Lauf beenden,
     berichten. Nicht auf rotem Fundament weiterbauen.
4. **Frischer-Kontext-Review** (vor dem Commit jeder Einheit): der Reviewer braucht einen
   Diff. Seit Stufe 4 stagt nicht mehr die Session, sondern `task-close.sh --stage` in
   Schritt 5 (`git add` prompt) — gib dem Reviewer deshalb `git diff HEAD -- <pfade>` als
   Diff-Quelle **und** nenne ihm die neuen Dateien ausdrücklich: untrackte Dateien stehen in
   keinem `git diff`, er muss sie direkt lesen (`git status --porcelain -uall -- <pfade>`
   zeigt sie). Dann einen **frischen Sub-Agent** starten (Agent-Tool, `general-purpose`,
   Modell wie unten) mit einem Prompt, der ihm explizit mitgibt: (a) **lies zuerst
   `.claude/skills/feature-review/SKILL.md`** und prüfe streng gegen dessen 7 Kriterien (er
   lädt den Skill NICHT von selbst); (b) der zu prüfende Diff ist `git diff HEAD -- <pfade>` plus
   die genannten neuen Dateien (gestaged ist noch nichts); (c) die
   Soll-Vorgabe ist die Task + die Spec/Report-Stelle (Pfad aus dem `Spec:`-Feld des
   Ledger-Kopfs); (d) **die Suiten sind bereits gelaufen** — er fährt sie NICHT nach, sondern
   prüft die im Auftrag zitierte Summary-Zeile gegen den Diff und macht höchstens gezielte
   Mutations-Proben (einen einzelnen Test lesen oder ausführen, um zu sehen, ob er ohne den
   Fix rot würde). Er sieht **nur** das — nicht deinen Bau-Verlauf.
   - **Modell:** `bash scripts/dev/review.sh risk` entscheidet (ohne Flag: alles noch nicht
     Committete, untrackte Dateien eingeschlossen — gestaged ist hier noch nichts).
     `standard` ⇒ `model: sonnet`, `xhigh` ⇒ `model: opus`. Welche Pfade riskant sind, steht in
     `scripts/dev/review-risk.txt` plus den Harness-Pfaden, nicht in diesem Text.
   - **Eigenes Verzeichnis:** je Reviewer `mktemp -d -p <Scratchpad der Session>` anlegen und
     im Prompt nennen, samt der Regel aus feature-review „Proben und Aufräumen": Proben nur
     mit `mktemp -d -p <sein Verzeichnis>`, nur eigene Pfade mit vollem Pfad löschen, nie per
     Glob. Kein fester Pfad unter `/tmp` mit eingebauter uid: der Runner hat eine andere.
   - **Zeitbudget 10 Minuten.** Liegt nach ~10 Minuten kein Urteil vor: den Agent stoppen
     (`TaskStop`) und **einmal** einen frischen mit engerem Prompt starten (nur die geänderten
     Dateien und die Kriterien 1–4 nennen). Bleibt auch der ohne Urteil → selbst gegen dieselben
     Kriterien reviewen und mit dem Urteil schließen:
     `bash scripts/dev/task-close.sh <ledger> <id> --review-note "selbst — Sub-Agent ohne Urteil" -m "…"`.
   Urteil — **Eine Runde ist die Regel** (Kevin, 2026-10-02):
   - `approve` → weiter zum Commit.
   - `request_changes` mit einem `blocker` oder einem **belegten** `wichtig` (konkrete Eingabe →
     falsches Ergebnis) → Punkte beheben, betroffene Schnelltests erneut, **einmal**
     re-reviewen. Danach gelöst → schließen; braucht Entscheidung →
     `bash scripts/dev/ledger.sh mark-question <ledger> <id> "<frage>"` (nicht raten).
     Max. 2 Runden: belegte Funde der zweiten Runde mit den Fällen des Reviewers als Tests
     beheben und schließen, keine dritte Runde; sonst Commit des Sauberen oder STOPP.
   - `nit`-Punkte blockieren nie: in derselben Runde ohne Re-Review miterledigen oder liegen
     lassen.
   - **Kein neuer Umfang mitten im Bau** außer bei einer Sicherheitslücke: neue Funde
     außerhalb der Task (eine Umgehung, ein Fehlalarm anderer Herkunft) gehen über die
     Aufsicht als Roadmap-Kandidaten in die Roadmap, nicht als Task in dieses Ledger.
   (Review-Granularität = Commit-Granularität. Ein **Kurz-Ledger** (≤ 3 Tasks) trägt im Kopf
   `Review: am Ende` — dann entfällt dieser Schritt pro Task und es gibt genau **einen**
   Gesamt-Review im Abschluss.)
5. **Schließen — nicht mehr `git commit`, sondern `task-close.sh`.** Es fährt das `Verify:`
   der Task selbst noch einmal, prüft Diff-Scan, Scope und Sec-Sperre, setzt den Haken mit
   der Summary-Zeile dieses Laufs als Evidenz und committet Code **und** Ledger in einem
   Commit — außerhalb dieser Session, damit keine der drei Behauptungen („grün", „fertig",
   „committet") von der Session selbst stammt:
   ```bash
   bash scripts/dev/task-close.sh <ledger> <id> --stage --review-note "approve (sonnet)" -m "<msg>"
   ```
   `--stage` stagt die Pfade aus `Dateien:` der Task (nur die, keine Verzeichnisse, auch
   Löschungen) — **nutze es**: `git add` prompt seit Stufe 4, ein Bau, der von Hand stagen
   will, bleibt im Prompt stehen.
   `git add`, `git commit`, `git checkout`, `git restore` und `git stash` prompten seit
   Stufe 4 (Kevins `settings.json`) — das ist Absicht, nicht ein fehlendes Recht; auch der
   Rot-Pfad oben (`git restore …`) fragt also einmal nach.
   **Die Exit-Codes sind Anweisungen, keine Meldungen:**
   - **0** — committet, weiter zur nächsten Task.
   - **2** — nicht (voll) gestagt, unbekannte Task, kaputte Eingabe: die genannten Dateien
     stagen (`git add -- <pfade>`) und erneut schließen.
   - **3** — die Suite ist rot, oder der Diff-Scan hat einen stummgeschalteten Test gefunden
     (`|| true`, `set +e`, `skip`, gelöschte Assertion): beheben, erneut schließen. Ist die <!-- review: ok Musterliste in der Anleitung -->
     Zeile bewusst so, trägt sie `# review: ok <grund>`.
   - **4** — blockiert: ein Pfad außerhalb der Task (`ledger.sh set-files` oder Datei aus dem
     Commit nehmen) oder etwas, das nie in dieses öffentliche Repo darf.
   - **74** — Infrastruktur: die Suite konnte gar nicht laufen → **STOPP** und berichten. Zwei
     Sonderfälle sind kein Stopp: eine Task **ohne `Komponente:`** (Handarbeit, z. B. „Kevins
     Handgriffe") wird gar nicht über `task-close.sh` geschlossen — offen lassen und im
     Abschluss berichten; und ein gescheitertes `git commit` (Recovery unten: einfach erneut
     schließen, der Aufruf ist wiederholbar).

   **Granularität:** `task-close.sh` schließt **eine** Task und macht **einen** Commit. Damit
   wandert auch der Review auf **pro Task** — ein Commit, der vor seinem Review fällt, ist
   genau das, was Schritt 4 verhindern soll; `Commit-Granularität: pro Komponente|pro
   Abschnitt` in einem älteren Ledger ist ab Stufe 4 gegenstandslos. Einzige Ausnahme bleibt
   das **Kurz-Ledger** (`Review: am Ende`, ≤ 3 Tasks): dort fallen die Commits bewusst vor dem
   einen Gesamt-Review über den Branch-Diff. **Nie einen roten Stand committen.**
   Commit-Body: Task-IDs + Stichwort.

## Abschluss (kein `[ ]` mehr offen)
1. **Bereit — zuerst:** Den Ledger-Kopf setzt `task-close.sh` beim Schließen der letzten
   offenen Task selbst von `aktiv` auf `Status: bereit`, im selben Commit (R-0083). Steht der
   Kopf danach noch auf `aktiv` — die letzte Task ging per `mark-skip` oder `[?]` zu, oder eine
   Handarbeit ohne `Komponente:` blieb offen —, von Hand: `ledger.sh status <ledger> bereit` als
   `chore(ledger)`-Commit. Die Roadmap-Zeile auf `bereit` zieht die Session in jedem Fall nach.
   Zuerst, weil `ledger.sh lint` ein `aktiv` ohne offene Task als Fehler wertet und
   `ledger_test` jedes echte Ledger lintet — der Gesamt-Schnellcheck fiele sonst über das eigene
   Ledger. Ab hier baut niemand mehr daran; Verifikation und PR stehen aus.
2. Gesamt-Schnellcheck: `bash scripts/tests/run.sh quick` (lint + unit); bei
   `Fast-Suite: vm` stattdessen `bash scripts/vm/iter.sh quick` (ohne `AH_ONLY`).
3. **Schwere Suite auf der VM — nur wenn nötig (path-gated, CLAUDE.md).** Was geplant ist, sagt
   `Heavy:` im Kopf: `none` → keine; `linux-full` → der `/test`-Weg unten; `scenario <flags>`
   → der Multibox-Lauf mit diesen Flags, **beim Nutzer anfragen**; `windows` → die Windows-VM
   gibt es erst mit Stufe 12, also „nicht verifiziert" melden. Ältere Ledger ohne `Heavy:`:
   `Warm-Profil` und `Abschluss: multibox` wie unten. Den Plan immer am realen Diff
   re-checken, in beide Richtungen, und eine Abweichung im Abschluss nennen.
   Erst den Branch-Diff prüfen (`git diff --stat main...`): Berührt er **heavy-relevante**
   Pfade? (`apps/server`-API/Gateway, `apps/ca-issuer`, `apps/gateway`, `apps/agent`,
   `apps/desktop` Connect/Tunnel/Enrollment, `docker-compose*.yml`, `Dockerfile`,
   `scripts/install|update`, FRP/PKI). **Wenn nein** (z. B. reine `docs/`-, Web-UI- oder
   Kleinkram-Änderung) → schwere Suite **überspringen** mit begründetem Vermerk, direkt zu
   Schritt 4. **Wenn ja:** dem `/test`-Skill folgen — Box warm
   → `run.sh quick` → `AH_ALLOW_REAL=1 run.sh integration` (+ `e2e` nur bei berührter
   `apps/web`/`apps/desktop`-Journey). Dabei das **`Warm-Profil` am realen Diff re-checken**,
   in beide Richtungen: `pond` geplant, aber keine Desktop-Journey im Diff → Single-Box
   reicht (zweite Box sparen); steht **`Abschluss: multibox …`** im Kopf ODER berührt der
   Diff Cross-Host-Pfade (FRP-Tunnel-Datenpfad, :8444-Provisioning, `build-deb/rpm`,
   `scripts/install|update`, mTLS/PKI) → den Multibox-Lauf **beim Nutzer anfragen**
   (fragen, nicht einfach starten — `multibox.sh` ist allowlisted, der Zügel ist deiner) und das Ergebnis in
   den PR-Body aufnehmen. Danach **`python3 scripts/vm/vm.py list`** prüfen (keine geleakten VMs —
   die Liste endet mit Exit 74, wenn auf dieser Lane etwas läuft, das niemand beansprucht)
   und `bash scripts/vm/reap.sh`. **Nur bei realem Pass weiter — SKIP ≠ grün.** (Die VMs tragen
   eine Frist und sterben beim nächsten `vm.py`-Aufruf danach — nur der single-box-Warm-Loop,
   kein `multibox`/`bake` ohne Nachfrage.)
4. **Review über den Branch-Diff** — welcher, sagt das `Review:`-Feld des Kopfs:
   - **`Review: am Ende`** (Kurz-Ledger, ≤ 3 Tasks): **ein** Frischer-Kontext-Review über den
     ganzen Branch-Diff (`git diff main...`, Sub-Agent wie in Schritt 4 der Iteration) — und **kein**
     `/code-review` hinterher: der eine Reviewer hat genau diesen Diff schon gesehen, der
     zweite Durchgang kostet nur Zeit.
   - **`Review: pro Task`** (Default für große Ledger): die Einheiten sind einzeln reviewt,
     aber niemand hat das Ganze gesehen → hier `/code-review` über den Branch-Diff.
   Echte neue Bugs als Tasks in den Ledger: Kopf zurück auf `aktiv` (Roadmap ebenso), fixen,
   erneut testen, dann wieder `bereit`.
5. **Erledigt, Push + Draft-PR** (der eine bewusst prompt-pflichtige Schritt — nach außen
   wirkend): **zuerst** den Ledger-Kopf auf `Status: erledigt` (bzw. `blockiert`, wenn
   `[?]`-Punkte offen bleiben; ein `chore(ledger)`-Commit) — vor dem Push, sonst kommt er nie
   in den PR und steht nach dem Merge auf `main` für immer auf `bereit`. Dann
   `git push -u origin <branch>`; den PR-Text schreibt
   `bash scripts/dev/review.sh pr-body <ledger> > <Scratchpad>/pr-body.md` (Spec, Roadmap-IDs,
   Heavy-Zeile, je Task Haken mit Evidenz und Review, `[~]`/`[?]` gesondert; eine Task ohne
   Evidenz heißt „unverifiziert"), das VM-Ergebnis kommt von Hand dazu; dann
   `gh pr create --draft --title "<type>: <feature>" --body-file <Scratchpad>/pr-body.md`.
   (Push und PR prompten, solange nicht allowlisted — das ist Absicht.)
6. **Mit dem PR:** die Roadmap-Zeile wie unter „Roadmap mitziehen" (`pr --pr "#<n>"`, ein
   Teil-Ledger `aktiv --pr`) — dafür braucht es die PR-Nummer. Schluss-Zusammenfassung im Chat;
   die `[?]`-Punkte klar auflisten — die entscheidet der Mensch.

## Recovery
- Granulare Commits ⇒ ein Fehlgriff = `git revert <commit>`, keine Handarbeit.
- `task-close.sh` ist wiederholbar: bricht es nach dem Haken ab (etwa weil `git commit`
  scheitert), setzt ein zweiter Lauf dieselbe Zeile neu und stapelt nichts.
- Der Loop begräbt nie einen roten Stand: **grün + committen**, ODER **zurücknehmen + `[~]`**,
  ODER **STOPP**. Kein vierter Weg.

## Feste Regeln
- Während des Loops **nur schnelle Suiten**. Schwere VM-Suite **nur im Abschluss**.
  **Nie** `run.sh integration|e2e|all` mitten im Loop, nie `bake` und nie `multibox`
  ohne Nachfrage (CLAUDE.md).
- Ehrlichkeit vor Fortschritt: nichts als `[x]`, dessen Suite nicht real grün lief.
- Surgical & zurückführbar: jede geänderte Zeile führt auf einen Ledger-Eintrag zurück.
- CLAUDE.md gilt vollständig (Sprache, Conventional Commits, SPDX, Doku-Pflege, DoD).
