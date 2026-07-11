<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Autonomes Arbeiten an AdminHelper mit Claude Code

Diese Anleitung beschreibt, wie du AdminHelper so weit wie möglich **autonom** mit Claude
Code weiterentwickelst — vom Feature-Wunsch (oder einem Fable-Audit-Report) bis zum fertigen
Draft-PR. Sie baut auf einer Erkenntnis auf: **du machst das Kernmuster längst von Hand.**
Dein früheres root-`tasks.md` war bereits eine _durable Task-Ledger_ mit verifizierbaren
Zielen pro Aufgabe. Dieses System formalisiert genau das.

**Alle Ledger leben unter [`tasks/`](tasks/)** — eine Datei pro Vorhaben (`tasks/<slug>.md`),
kein Anhängen an eine Sammel-Datei mehr. Jedes Ledger trägt im Kopf ein Feld `Status: aktiv |
erledigt | blockiert`, damit `/feature-build` das aktive findet. Konvention: `tasks/README.md`.

## Die Idee in fünf Sätzen

1. **Ledger-getrieben.** Jede Arbeit lebt in einer Markdown-Ledger aus kleinen, einzeln
   verifizierbaren Tasks. Die Ledger ist die einzige Wahrheit über den Fortschritt und
   übersteht Kontext-Resets — das macht lange autonome Läufe erst möglich.
2. **Klein genug.** Eine Task ≈ eine fokussierte Änderung, möglichst eine Komponente,
   mit einem konkreten `Verify:`. Nur so kann sie ohne Rückfrage abgearbeitet werden.
3. **Ein Gate.** Der einzige feste menschliche Kontrollpunkt ist das **Design-Gate** nach
   der Planung. Danach läuft Bauen → Testen → PR autonom.
4. **Granulare Commits = einfache Recovery.** Ein Commit pro Task auf einem Feature-Branch.
   Geht etwas schief: `git revert <commit>` statt Handarbeit.
5. **Test-Tiering.** Schnelle Suiten laufen nach jeder Task; die schwere crabbox-Suite erst
   am Ende, einmal.

## Der Zyklus

| Phase | Aufruf | Ergebnis |
|---|---|---|
| **1 · Design** | `/feature-plan <idee>` | **Interaktiv** (fragt bei echter Mehrdeutigkeit sofort per Rückfrage): erzeugt `docs/features/<slug>.md` (Spec) + `tasks/<slug>.md` (Ledger). **Stoppt am Design-Gate.** |
| **2 · Freigabe** | _du_ | Spec + Ledger lesen/anpassen, offene Fragen beantworten. |
| **3 · Build** | `/feature-build tasks/<slug>.md` | Task für Task: umsetzen → schnelle Tests → **frischer Review** (`feature-review`) → 1 Commit/Task auf `feature/<slug>`. |
| **4 · Verify + PR** | _(automatisch am Ende von Phase 3)_ | `run.sh quick` → schwere crabbox-Suite → `/code-review` (ganzer Branch) → **Draft-PR**. |

Alles läuft auf **Opus** (`/model opus` oder `claude --model opus`). Fable brauchst du hier
nicht — die Qualität an den Hebelpunkten (Design, Review) trägt Opus für die allermeisten
Features; für ein besonders kniffliges Design kannst du Phase 1 einmalig mit Fable fahren.

**Zwei Review-Ebenen (dein Reviewer-„dazwischen").** Der Code wird nie ungeprüft committet:
(1) **pro Commit-Einheit** ein **frischer Sub-Agent** (`feature-review`), der nur den Diff +
die Task + feste Kriterien sieht — unvoreingenommen, weil er den Bau-Verlauf nicht kennt;
(2) am Ende ein `/code-review` über den ganzen Branch-Diff. Ebene 1 fängt den einzelnen
Fehltritt sofort, Ebene 2 die Wechselwirkungen. `feature-review` läuft auch standalone
(`/feature-review`, oder `/loop /feature-review` für einen frischen Prüf-Durchlauf).

### So startest du konkret

```bash
# Opus-Session mit reduzierten Nachfragen (Edits/Tests/Git ohne Prompt):
claude --model opus --permission-mode acceptEdits
```

```text
# 1. Planen (stoppt am Gate):
/feature-plan Pro-Connection-Notiz: freies Textfeld an jeder Verbindung, in Web + Desktop editierbar

# 2. Du liest docs/features/connection-note.md + tasks/connection-note.md, passt an, gibst frei.

# 3. Autonom bauen bis Draft-PR:
/feature-build tasks/connection-note.md
```

Der einzige Prompt, den du im autonomen Lauf standardmäßig noch siehst, ist das
**PR-Öffnen** am Ende (bewusst prompt-pflichtig gelassen, weil es nach außen wirkt). Willst
du auch das promptlos: `Bash(gh pr create:*)` in `.claude/settings.json` → `allow`
aufnehmen, oder die Session mit `--dangerously-skip-permissions` fahren (nur auf einem
Branch sinnvoll).

## Zweiter Einstiegspunkt: einen Fable-Report abarbeiten

Der „Report fixen"-Fall ist derselbe Mechanismus — die Report-Funde _sind_ ein Ledger unter
`tasks/`:

```text
/feature-build tasks/audit-fixes.md
```

`tasks/audit-fixes.md` ist die Fortschritts-Ledger zum letzten Audit; das Fix-Detail je Fund
steht in `fabelreport.md` (Root, gleiche IDs). Für sehr große Backlogs (die 681 Funde)
startest du es unter `/loop`, damit es batchweise über viele Iterationen läuft:

```text
/loop /feature-build tasks/audit-fixes.md
```

## Parallel-Betrieb: mehrere Lanes gleichzeitig

Mehrere Vorhaben laufen parallel, indem jedes Ledger seine eigene **Lane** bekommt: ein
Git-Worktree + eigene Opus-Session + eigene warme crabbox-Box. Geplant wird weiterhin
seriell (das Design-Gate braucht dich); gebaut wird parallel. **Nie zwei Builds auf
demselben Ledger** — der Ledger ist die einzige Fortschritts-Wahrheit, es gibt kein Locking.

```bash
# 1. Planen wie gehabt (/feature-plan → Gate → Freigabe). Danach committet die
#    Plan-Session Spec + Ledger auf main — Worktrees sehen nur Committetes.
# 2. Lane aufmachen (Worktree ../AdminHelper-<slug>; .devenv.sh als Symlink,
#    settings.local.json als Kopie — Claude Code schreibt sie bei Grants):
bash scripts/dev/lane.sh new <slug>
# 3. Lane starten (eigenes Terminal/tmux-Pane):
cd ../AdminHelper-<slug> && claude --model opus --permission-mode acceptEdits
#    → /feature-build tasks/<slug>.md
# 4. Lane gemergt / Feierabend:
bash scripts/dev/lane.sh done <slug>   # reapt die Lane-Boxen, räumt Worktree + Branch
```

Mechanik dahinter:

- **Eigener Pond pro Lane.** `crabbox_lib.sh` leitet aus dem Checkout-Namen eine
  Lane-Kennung ab (`AdminHelper-conn-note` → Pond `ah-warm-conn-note`; Haupt-Checkout →
  historisches `ah-warm`; `AH_LANE` überschreibt). `crabbox_reap.sh` kehrt nur den eigenen
  Pond — Lanes können sich nicht gegenseitig die Boxen stoppen. Leases sind host-global
  serialisiert (flock — parallele Warmups hängen den Provider); Bootstrap und Iterationen
  laufen parallel. crabbox bindet eine Lease zusätzlich an den Checkout-Pfad, der sie
  geleast hat (fremder Checkout müsste explizit `--reclaim`) — Lanes syncen also auch nie
  versehentlich in fremde Boxen. Der Sync aus Worktrees ist validiert; er trägt nur den
  Source-Tree, **auf der Box liegt kein `.git`** — einziger on-box-Nutzer ist das
  Agent-Makefile (`git describe`), das auf `dev` zurückfällt; `build-deb/rpm` bekommen
  `VERSION` ohnehin explizit.
- **`Fast-Suite: crabbox` im Ledger-Kopf.** Eine Lane hat keine lokalen
  Toolchain-Artefakte (venvs/`node_modules`/`target`), und N parallele lokale Suiten
  würden die Dev-Box überlasten (plus Kollision auf der geteilten Test-DB). Der Build
  fährt deshalb das Task-`Verify:` via `crabbox_iter.sh --cmd '…'` und die
  Komponenten-Schnellsuite via `AH_ONLY='<komponenten>' crabbox_iter.sh quick` auf der
  warmen Lane-Box (~1,5–3,5 min pro Iteration).
- **`Warm-Profil:` im Ledger-Kopf.** `desktop` (eine volle Box — Stack, Agent und GUI
  testen dort zusammen) reicht für fast alles; `pond` (2 Boxen) nur für Desktop-Journeys;
  Cross-Host-Pfade bekommen `Abschluss: multibox <flags>` — ein einmaliger, weiterhin
  ask-first-Lauf am Ende, keine warme Dauer-Infrastruktur. `/feature-plan` leitet das aus
  der Spec ab, `feature-build` re-checkt es am realen Branch-Diff.

Regeln:

- **Der Haupt-Checkout bleibt auf `main`** — nur Planen, Mergen, Rebasen. Gebaut wird
  ausschließlich in Lanes.
- **Lanes komponenten-disjunkt schneiden.** Das Gate prüft gegen aktive Lanes:
  Komponenten, geteilte Contracts (API-Schemas, Migrationen, FRP-Format, Tauri-Commands),
  primäre `docs/`-Seiten. Überlappt es → seriell statt parallel.
- **PRs landen einzeln.** Nach jedem Merge in den verbleibenden Lanes
  `git rebase origin/main` + einmal `crabbox_iter.sh quick`. Bekannte, triviale
  Rebase-Konflikte: `CHANGELOG.md` (Unreleased) und geteilte docs-Seiten — additiv.
- **Kosten:** pro Lane eine warme beast-Box (pond: zwei) über Stunden; Tokens ≈ wie
  seriell, nur die Burn-Rate steigt (Rate-Limits drosseln ggf. von selbst). Mehr als
  2–3 Lanes stauen an deinen Gates/Reviews, nicht am Compute.

## Was eine Task „autonomietauglich" macht

Das ist der Punkt, an dem die meiste Qualität entsteht — `/feature-plan` achtet darauf, aber
prüf es am Gate mit:

- **Eine Komponente, ≤ ~3 Dateien.** Zwei Komponenten (z. B. Server-API _und_ Web-Formular)
  → zwei Tasks.
- **Ein konkretes `Verify:`.** Ein Befehl/Assertion, der grün/rot sagt. „Sieht gut aus" ist
  kein Verify.
- **Unabhängig testbar**, Reihenfolge nur bei echter Abhängigkeit.
- **Keine Design-Entscheidung in der Task.** Steckt eine drin, ist die Task zu groß — die
  Entscheidung gehört als offene Frage in die Spec und wird am Gate geklärt.
- **Neuer Flow ⇒ Task enthält den Test. Neue Datei ⇒ Task nennt den SPDX-Header.**

## Recovery — wenn etwas schiefgeht

- **Ein einzelner Fehlgriff:** `git revert <task-commit>` nimmt genau diese Task zurück, der
  Rest bleibt. Genau dafür committet der Loop pro Task.
- **Ein Fix macht Tests rot** und ist nicht schnell lösbar: der Loop nimmt ihn selbst zurück
  (`git checkout -- <datei>`), markiert die Task `[~] (verworfen: Test rot)` und macht weiter.
- **Rotes Fundament** (Test rot, unabhängig von der Änderung): der Loop **stoppt** und
  berichtet, statt weiterzubauen.
- **Ganzes Feature verwerfen:** der Branch ist isoliert — `git switch main && git branch -D
  feature/<slug>` und alles ist weg.
- **`[?]`-Tasks** (mehrdeutig/destruktiv) überspringt der Loop bewusst und legt sie dir am
  Ende zur Entscheidung vor.

## Die Automatisierungs-Schicht (`.claude/`)

> **`.claude/` wird per Whitelist geteilt** (das Repo ist PUBLIC). Versioniert sind die
> wiederverwendbare Automatisierung: `settings.json` (Permissions + Hook) und `skills/`.
> **Draußen bleibt nur `settings.local.json`** — sie trägt jetzt sowohl das crabbox-Token
> als auch die Proxmox-Infra (`env`, aus `settings.json` dorthin verschoben, damit keine
> Homelab-Details öffentlich werden). Neue `.claude/`-Dateien sind per Default ignoriert, bis
> du sie in der `.gitignore`-Whitelist freigibst.

Damit „autonom" nicht an ständigen Prompts scheitert, ist Folgendes eingerichtet:

- **`.claude/settings.json` → `permissions.allow`**: schnelle Tests/Linter (`pytest`,
  `ruff`, `go test/vet`, `cargo test/clippy/fmt`, `npm run`), Git-Befehle inkl. Recovery
  (`switch`, `restore`, `checkout`, `revert`), der Test-Aggregator, der crabbox-Warm-Loop
  (`crabbox`-Subcommands + `crabbox_warm/iter/reap.sh` + `artifacts pull`) laufen **ohne
  Nachfrage**. Bewusst _nicht_ freigegeben (prompten weiter — der eine bewusste Endstopp bzw.
  Kostengate): `git push`, `gh pr create`, alles unter `rm`/`reset --hard`, sowie crabbox
  `prewarm/job/checkpoint/image/bake` und `crabbox_multibox.sh` (least viele VMs).
- **Kein Auto-Format-Hook.** (Ein früherer PostToolUse-Formatter wurde entfernt: er
  reformatierte ganze Dateien → gegen die Surgical-Regel und die Doku-Commits, und brach
  iterative `Edit`s. Formatierung fangen ohnehin die `ruff format --check`/`npm run lint`-
  Gates.) `scripts/dev/format-file.sh` bleibt als **manuelles** Werkzeug (`bash scripts/dev/
  format-file.sh <datei>`).
- **Skills** unter `.claude/skills/`: `feature-plan` (interaktiv), `feature-build`,
  `feature-review` (frischer-Kontext-Reviewer, auch standalone), dazu das bestehende
  `test` (crabbox-Anleitung).

### Erweiterungsideen (noch nicht gebaut)

- **`/feature-verify`** als eigener Skill, falls du die schwere Suite unabhängig vom Build
  neu fahren willst (aktuell macht `feature-build` das am Ende selbst).
- **Stop-Hook**, der beim Sitzungsende offene `[?]`-Tasks der aktiven Ledger auflistet.
- **Feature-Issue-Template** in `.github/ISSUE_TEMPLATE/`, falls du doch pro Feature ein
  Tracking-Issue willst (aktuell bewusst lokale Ledger).

## Grenzen & bewusste Entscheidungen

- **crabbox kostet VM-Leases.** Der Build-Loop fährt die schwere Suite genau einmal am Ende
  (deine Wahl „Auto-crabbox"). Die Boxen self-reapen; trotzdem prüft der Loop danach
  `crabbox list` auf Leichen.
- **Plattform-Code** (Windows-Agent, RDP/SSH pro OS) wird laut CLAUDE.md manuell verifiziert
  — solche Tasks markiert `/feature-plan` als `[?]` bzw. mit manuellem Verify-Schritt.
- **Kein Ersatz für Review.** Das Design-Gate und der finale PR-Review bleiben deine
  Entscheidung; der Loop bereitet vor, du gibst frei.
- Es gilt weiterhin **`CLAUDE.md`** (Surgical Changes, Doku-Pflege, Conventional Commits,
  SPDX, Test-DoD) und **`CONTRIBUTING.md`**. Dieses Dokument beschreibt nur, _wie_ die Arbeit
  fließt — nicht neue Regeln.
