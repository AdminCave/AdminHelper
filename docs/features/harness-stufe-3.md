<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness Stufe 3 — Ausführung zuerst

Stand 2026-09-10 · Status: Spec zum Design-Gate · Ledger: `tasks/harness-stufe-3.md` · Roadmap-Zeile R-0003 (schließt R-0021, R-0022 ein)

## Problem / Motivation

Alle sechs release-blockierenden Defekte der 0.43.x/0.44.0-Reihe kamen aus Ausführung, keiner aus statischer
Review. Vier davon hätte der schwere Tier gefangen, drei die Artefakt-Assertionen. Beides existiert nur als
Handarbeit: den Capstone startet Kevin von Hand vor einem Release, die Release-Assertionen fehlen ganz.

- `release.yml` baut den Agent statisch (`make build-linux`), prüft es aber nicht: ein Umbau auf einen
  Inline-`go build` würde wieder dynamisch gegen glibc 2.39 linken (Defekt `4120005`). Das `.deb` wird in
  `build-deb.sh:48` auf xz-Member geprüft, das ausgelieferte Artefakt im Workflow nicht. Die minisign-Signatur
  wird geschrieben, aber nie gegen den in `scripts/update.sh` gepinnten Public Key verifiziert. Die
  Windows-`.exe` wird nie ausgeführt, das MSI nie installiert (`desktop-windows` ist `continue-on-error`).
- Die Versions-Stellen (`tauri.conf.json`, `Cargo.toml`, `Cargo.lock`, `CHANGELOG`, 36 Sidebar-Footer, zwei
  News-Callouts) prüft nur ein Inline-Schritt für `tauri.conf.json`; die Footer hingen drei Releases lang.
- `go test` läuft ohne `-race`; der Agent ist nebenläufig (Reporter, Monitor, Service).
- Es gibt keinen Wochenlauf: `run.sh all` und der Multibox-Capstone laufen, wenn Kevin daran denkt. Ihre
  Ergebnisse werden nirgends festgehalten, ein roter Lauf hat keine Klassifikation (Regression? Flaky?
  Umgebung?), und jede Bewertung passiert im Kopf.
- `crabbox_multibox.sh` hat vier weitere stille Skips (Agent-Repo/CA-Flip ohne Fingerprint, Desktop-Lease,
  moncheck-Lease, `--enforce`) und meldet bei null erreichten Agents `0 >= 0` als ok (R-0021);
  `--capstone` setzt `ENFORCE` nicht, der `MTLS_ENFORCE`-Guard lief also in keinem Release-Capstone (R-0022).
- Fünf Desktop-Specs (`login-error`, `logout`, `monitoring-alerts`, `connection-editor`, `theme-toggle`)
  werden von keinem `desktop_e2e_*.sh` gefahren.
- Der Upgrade-Pfad (Vorgänger-Release → aktueller Stand, Alembic beider Dienste, `update.sh`) wird nur beim
  Release selbst und nur auf Kevins Server erprobt.

## Ziel & Nicht-Ziele

**Ziel.** Die zwei Dinge, die 6 von 6 Defekten gefangen hätten, laufen: Artefakt-Assertionen im Release-Workflow
und ein Wochenlauf `heavy.sh weekly`, den Kevin in `tmux` startet. Der Wochenlauf klassifiziert rote Befunde
mechanisch in **INFRA**, **FLAKY**, **unbestätigt**, **extern** und **REG**, schreibt seine Historie in das
private Repo und macht aus einer bestätigten Regression eine Roadmap-Zeile plus Kurz-Ledger, ohne dass ein
Umgebungsfehler als Produktbug erscheint. Alles läuft auf den heutigen crabbox-Wrappern, damit Stufe 2 die
Implementierung darunter tauschen kann und dieselben Summary-Zeilen liefern muss.

**Nicht-Ziele.** Kein Timer, kein Cron, kein Issue-Posting. Kein neuer VM-Client (Stufe 2). Kein Windows-Lauf
(Stufe 12; der Wochenlauf hat den Platz dafür). Keine `roadmap.py` (Stufe 5; Roadmap-Zeilen entstehen als
Tabellenzeile per Skript-Append). Keine Suite-Retries (`pytest --reruns`, Playwright `retries`): in den ersten
fünf Wochenläufen bleibt `R reruns` 0, damit die Quarantäne kalibriert. Kein Gate-Flip des MSI-Jobs (Stufe 12).
Keine Änderung an `AH_OUT_DIR` (`.crabbox-out` bis Stufe 2).

## Betroffene Komponenten & Dateien

| Bereich | Dateien |
|---|---|
| Release-Assertionen | `.github/workflows/release.yml` (Jobs `agent`, `desktop-windows`, `release`, neu `agent-windows-smoke`), `.github/workflows/ci.yml` (Job `agent`: `-race`) |
| Versions-Check | neu `scripts/release/check-versions.sh`, neu `scripts/tests/check_versions_test.sh`, `.claude/rules/release.md` |
| Wochenlauf | neu `scripts/tests/heavy.sh`, neu `scripts/tests/heavy_test.sh`, `scripts/tests/crabbox_multibox.sh`, neu `scripts/tests/desktop_e2e_misc.sh`, `scripts/tests/run.sh` (e2e-Liste, integration-Liste) |
| Upgrade-Pfad | neu `scripts/tests/upgrade_path_test.sh` |
| Privates Repo (gitignored) | `tasks/private/history.csv`, `tasks/private/seen.md`, `tasks/private/ROADMAP.md` (Append unter „Neu") |
| Hook / Skill | `scripts/dev/hooks/session-status.sh` (Wochenlauf-Zeile), `.claude/skills/test/SKILL.md` (neu geschrieben) |
| Doku | `docs/developer/cicd.html`, `docs/en/developer/cicd.html`, `DEVELOPMENT.md`, `CHANGELOG.md` |

## Design

### 3a Release- und CI-Assertionen

- **Agent statisch:** nach `make build-linux build-windows` im Job `agent`: `file apps/agent/bin/adminhelper-agent`
  muss `statically linked` enthalten **und** `objdump -T` darf kein `GLIBC_`-Symbol liefern. Beides in einem
  Schritt „Assert static agent binary", Exit 1 mit den beiden Ausgaben.
- **Ausgeliefertes `.deb`:** im Schritt „Collect artifacts" `ar t dist/adminhelper-agent_*.deb | grep -q '\.zst$'`
  ⇒ Fehler. Der Guard in `build-deb.sh` bleibt; hier wird das Artefakt geprüft, das hochgeladen wird.
- **Signatur gegen den gepinnten Key:** direkt nach `minisign -S` im Job `release`: Public Key aus
  `scripts/update.sh` (`MINISIGN_PUBKEY=…`) extrahieren, `minisign -V -P "$PUB" -m release/SHA256SUMS`. Ein
  Secret, das nicht zum gepinnten Key passt, bricht den Draft ab statt Nutzer-Installationen.
- **Windows-Binary läuft:** neuer Job `agent-windows-smoke` (`windows-latest`, `needs: agent`, nur auf Tags):
  Artefakt `agent` laden, `.\adminhelper-agent-windows-x86_64.exe version` muss die Tag-Version drucken.
  Hart, ~1 min.
- **MSI installiert und deinstalliert:** im Job `desktop-windows` nach dem Build `msiexec /i <msi> /qn /norestart
  /l*v msi.log`, Assertion `Installation success or error status: 0` im Log und Existenz der `adminhelper.exe`
  unter `%ProgramFiles%`, dann `msiexec /x <msi> /qn`; `msi.log` als Artefakt. Der Job bleibt
  `continue-on-error: true` bis zum Gate-Flip in Stufe 12 (Frage 5).
- **`go test -race`:** Job `agent` in `ci.yml`: `go test -race -cover ./...` (gcc auf ubuntu-latest vorhanden).
  Gleiche Zeile in `run.sh` für den Go-Step, wenn `gcc` vorhanden ist (sonst wie heute, mit Log-Hinweis).
- **`scripts/release/check-versions.sh <X.Y.Z>`:** prüft alle Stellen aus `.claude/rules/release.md`:
  `tauri.conf.json` `version`, `Cargo.toml` `version`, `Cargo.lock` Paket `adminhelper`, `CHANGELOG.md`
  Abschnitt `## [X.Y.Z]`, alle Sidebar-Footer (`<span>vX.Y.Z</span>`, Anzahl der Dateien ≥ 36, keine andere
  Version), News-Callouts `Was ist neu in X.Y.Z` / `What's new in X.Y.Z`. Druckt je Stelle `ok`/`FEHLT`, Exit 1
  bei einem Treffer. Ersetzt den Inline-Schritt „Verify the desktop version matches the tag" in `release.yml`.
  Hermetischer Test mit Fixture-Baum (alle Stellen richtig; ein Footer alt; CHANGELOG-Abschnitt fehlt).

### 3b `heavy.sh` — Terminal-Entrypoint des Wochenlaufs

```
bash scripts/tests/heavy.sh all|capstone|weekly [--base <sha>] [--no-second-vm] [--notify]
```

- **Nur Wrapper.** `all` = `crabbox_warm.sh desktop` → `crabbox_iter.sh all --strict` (setzt auf der Box
  `AH_ALLOW_REAL=1 AH_CAPTURE=1`, holt `.crabbox-out/**` inklusive `last-all.json` zurück) → Warm-Box bleibt
  stehen (TTL). `capstone` = `crabbox_multibox.sh --capstone --strict` (mit R-0022 enthält `--capstone` jetzt
  `--enforce`; Frage 4). `weekly` = `all` → `capstone` (→ `windows` ab Stufe 12), seriell, Capstone nur nach
  grünem oder klassifiziertem `all` (sieben VMs brennen sonst in einen bekannten Fehler).
- **Vorab:** `crabbox list` — fremde Boxen (nicht in `warm.env`, nicht im eigenen Pond) ⇒ Exit 74 mit Liste,
  keine Aufräumaktion an Kevins Warm-Boxen. `crabbox doctor` rot ⇒ 74.
- **Ergebnisse:** `$AH_OUT_DIR/weekly/<jjjj-mm-tt-hhmm>/` mit `report.md`, den gepullten Artefakten
  (`last-all.json`, Screenshots, Logs) und `multibox.log`. `report.md` beginnt mit genau einer Zeile
  `PASS` | `FAIL` | `UNVERIFIED (<grund>)`, dann die Summary-Zeilen **wörtlich** (`run.sh[all]: …`,
  `crabbox_multibox: …`), dann die Klassifikationstabelle, die REG-Kandidaten, die `audit.yml`-Zeile und die
  VM-Liste danach. Nie eine Bewertung, nur Fakten.
- **Historie:** `tasks/private/history.csv` (Spalten `datum,commit,tree_hash,ebene,schritt,ergebnis,sekunden,vm`;
  `ergebnis` ∈ `pass|fail|flaky|infra|unbestaetigt|extern|reg`) — eine Zeile je Schritt je Lauf, plus eine
  Zeile `ebene=all|capstone` mit dem Gesamtergebnis. Nach dem Lauf `git -C tasks/private add history.csv
  seen.md ROADMAP.md && git -C tasks/private commit -qm "weekly <datum>"` (kein Push; das bleibt Kevin).
  Fehlt das private Repo, schreibt `heavy.sh` die Dateien trotzdem und meldet es im Report.
- **`audit.yml`-Zeile:** anonymer Aufruf `https://api.github.com/repos/AdminCave/AdminHelper/actions/workflows/audit.yml/runs?per_page=1`
  (Public-Repo, kein Token, `timeout 10`): `conclusion` + Datum in den Report; `failure` ⇒ REL-Kandidat als
  Roadmap-Zeile `deps-audit` (Dedup „offen bis grün": `seen.md` `deps-audit · open|resolved`, eine Zeile je roter Phase).
- **Benachrichtigung:** `--notify` postet die Kopfzeile des Reports an `AH_NOTIFY_URL` (ntfy-/Webhook-URL aus
  `.devenv.sh`), Default aus (Frage 1).
- **Exit:** 0 = PASS, 1 = FAIL (mindestens ein REG-/unbestätigt-/extern-Befund oder roter Capstone), 74 =
  UNVERIFIED (Infra: Exit 74 der Wrapper, `strict-failed: … (SKIP)` auf der Box, Doctor rot, fremde Boxen).

### Klassifikation (der Kern von 3b)

Für jeden Schritt aus `last-all.json` mit `result=fail` bzw. jede rote Multibox-Assertion:

1. **INFRA** — der Lauf selbst lieferte Exit 74 oder `strict-failed: <step> (SKIP)`: der Schritt konnte nicht
   laufen. Ergebnis `infra`, Report-Kopf `UNVERIFIED`, **nie** REG (Skeptiker 3 #3).
2. **Wiederholung auf derselben Box:** bis zu drei Läufe nur dieses Schritts (`crabbox_iter.sh all --strict --step
   <name>` mit `AH_NO_SYNC=1`; für die Desktop-Suiten spec-genau über `AH_SPEC`). Ein grüner Lauf darunter ⇒
   **FLAKY**: Zeile in `tasks/private/seen.md` (`quarantine · <schritt> · <datum> · <zähler> · Ablauf +30 d`) und
   `history.csv` `flaky`. Drei identisch rote Läufe (gleicher fehlender Marker bzw. gleiche erste
   Assertions-Zeile) ⇒ Kandidat.
3. **Zweite frische VM** (Standard; `--no-second-vm` überspringt und lässt den Kandidaten `unbestätigt`):
   `heavy.sh` legt einen Worktree `.crabbox-worktrees/w2` auf HEAD an und warmt dort per `AH_LANE=w2
   crabbox_warm.sh desktop` eine zweite Box (eigener Pond, eigenes `warm.env`, wie jede Lane); dort läuft der
   Schritt einmal. Grün ⇒ **unbestätigt** (`history.csv`, Report-Abschnitt „Kevin sichtet", kein REG).
   Rot ⇒ weiter.
4. **Gegenprobe gegen den letzten PASS-Commit:** `--base <sha>`, Default = jüngste `history.csv`-Zeile mit
   `ebene=all` und `ergebnis=pass` (nicht `main`: auf `main` wäre die Gegenprobe leer — Skeptiker 3 #23). Im
   Worktree `w2` wird `<sha>` ausgecheckt und derselbe Schritt auf der zweiten Box gefahren (der Sync trägt
   den Basis-Baum, `crabbox_iter.sh` berechnet `head`/`tree_hash` aus dem Worktree). **Basis grün, HEAD rot
   ⇒ REG.** **Basis ebenfalls rot ⇒ extern** (Umgebung, Abhängigkeit, Netz — nicht der Code seit dem letzten
   PASS): `history.csv` `extern`, Report-Abschnitt „Kevin sichtet", kein REG. Abweichung zur Roadmap-Formulierung
   („Gegenprobe rot ⇒ REG"): die Wortwahl dort ist ein Fehler, die Logik hier ist die gemeinte (Frage 2).
   Gibt es noch keinen PASS in `history.csv` (erste Läufe), entfällt Schritt 4 und der Kandidat bleibt
   `unbestätigt`.
5. **REG:** Zeile unter „Neu" in `tasks/private/ROADMAP.md` (`Klasse REG`, Quelle `weekly <datum> · <commit> ·
   Zweit-VM rot · Basis <sha> grün`, Ablauf `nie`) **und** Kurz-Ledger `tasks/reg-<datum>-<schritt>.md`
   (`Status: geplant`, `Komponente:` statt `Dateien:`, Verify-Zeile in Flag-Form, Beweis-Absatz mit den drei
   Läufen). Die Freigabe bleibt Kevins Haken (D4). Dedup: gleicher Schritt + gleiche Assertions-Zeile in den
   letzten 30 Tagen ⇒ nur `history.csv`, keine zweite Zeile.

Der Worktree `w2` und seine Box gehören `heavy.sh`: nach dem Lauf `crabbox_reap.sh --pond ah-warm-w2` und
`git worktree remove`. Kevins Warm-Box (`ah-warm`) bleibt unberührt.

### `desktop_e2e_misc.sh`

Fährt die fünf verwaisten Specs nacheinander gegen den e2e-Stack (gleicher Aufbau wie `desktop_e2e_live.sh`,
`AH_SPEC` wählt einen einzelnen aus); Ausgabe je Spec eine Zeile `spec <name>: pass|fail`, Exit 1 bei einem
Fail, 75 bei fehlender Voraussetzung. Aufnahme in die e2e-Liste von `run.sh`. Wo ein Spec eine Voraussetzung
braucht, die es im Stack nicht gibt (z. B. eine Alert-Quelle für `monitoring-alerts`), meldet der Builder
`[?]` statt den Spec zu verbiegen.

### 3c `upgrade_path_test.sh`

Integration-Layer, dep-gated (Docker, Netz zu ghcr.io und GitHub), unter `--strict` Required auf der
`linux-full`-Box, nicht auf der Dev-Box. Ablauf: (1) letzten veröffentlichten Tag ermitteln (anonyme GitHub-API,
Prereleases ausgeschlossen); (2) Stack aus `ghcr.io/admincave/*:<tag>` hochfahren (Compose-Override mit den
Image-Tags, `DOMAIN=<box-ip>`), Seeds über `e2e_api.py` (Server, Verbindung, Agent-Report); (3) Wechsel auf
die aus dem Checkout gebauten `adminhelper-test/*`-Images (wie `integration_stack_test.sh`), Start ⇒ beide
Dienste laufen `alembic upgrade head` beim Start; Assertion: Seeds unverändert lesbar, ein neuer Agent-Report
landet; (4) `scripts/update.sh --ref <tag>` real gegen einen zweiten Stack im Vorgänger-Stand: Bundle-Download,
minisign-Verifikation, atomarer Swap, `docker compose ps` gesund. Schritt 4 hat eigene Marker und darf mit
`75` enden, wenn das Release kein Runtime-Bundle hat (ältere Tags).

### Hook, Skill, Doku

`session-status.sh` Zeile 4: `Wochenlauf: <datum> (<n> d): PASS|FAIL|UNVERIFIED` aus dem jüngsten
`report.md`, sonst `kein Report`; Warn-Trigger „Release ohne grünen Wochenlauf" bleibt Stufe 13 (Skript-Sperre).
`.claude/skills/test/SKILL.md` wird neu geschrieben: `quick` lokal (`verify.sh all --strict`), `all|capstone|weekly`
**drucken** den `tmux`-Startbefehl und enden, `status` liest den jüngsten Report, Leak-Regel, Zweit-VM-Regel,
Rhythmus-Empfehlung (Freitagabend), die Pitfalls bleiben. `docs/developer/cicd.html` DE+EN: Abschnitte
„Release-Assertionen" und „Wochenlauf (heavy.sh)" mit Klassifikationstabelle und Exit-Codes; `DEVELOPMENT.md`:
heavy.sh, `history.csv`, `AH_NOTIFY_URL`; `CHANGELOG.md` Unreleased.

## Trade-offs & Alternativen

- **Wrapper-only statt eigener Klon-Logik:** kostet in Schritt 3/4 eine volle Hydrierung (~40 min, weniger mit
  Fat-Template), spart aber jede Zeile, die Stufe 2 wegwerfen müsste. Alternative „Zweit-VM überspringen"
  liefert nur `unbestätigt`, nie REG — der Schalter `--no-second-vm` existiert für knappe Kapazität.
- **Worktree-Lane für Zweit-VM und Gegenprobe:** nutzt die vorhandene Lane-Mechanik (`cbx_lane`, `AH_LANE`)
  statt eines zweiten Sync-Pfads; Nachteil: zwei `warm.env`, die `heavy.sh` selbst aufräumt.
- **Roadmap-Append per Skript vor Stufe 5:** eine Zeile anhängen ist trivial und reversibel; die
  Row-Count-Invariante und `flock` kommen mit `roadmap.py`. Bis dahin: `.bak` vor dem Schreiben.
- **`-race` verdoppelt die Go-Testzeit** (~35 s → ~1–2 min im CI); dafür fängt es die Klasse Bug, die kein
  Review sieht.
- **MSI-Assertion ohne Gate-Flip:** ein roter MSI-Job bleibt sichtbar, blockiert aber nicht — bewusst, bis die
  Windows-VM (Stufe 12) die Journeys deckt.

## Risiken & Rollback

- Erste Wochenläufe sind verrauscht (Desktop-Kette flakt): die Quarantäne fängt es, `R reruns` bleibt 0,
  Kevin sieht im Report jede Zeile. Rollback: `heavy.sh` nicht starten; nichts läuft ohne Start.
- Kapazität: `all` + Capstone sind bis zu acht VMs; der Vorab-Check bricht mit 74 ab, wenn fremde Boxen laufen.
  Der Proxmox-Host steht laut Kevins Zahlen unter Speicherdruck (Swap fast voll) — vor dem ersten Capstone
  klären, was swappt; `heavy.sh` kann Speicher nicht prüfen (kommt mit `vm.py doctor`, Stufe 2).
- `--capstone` mit `--enforce` (R-0022) kann beim ersten Lauf rot sein, weil der Guard nie lief — das ist ein
  Fund, kein Infra-Fehler.
- `agent-windows-smoke` auf Tags kostet ~1 min Windows-Runner je Release; harmlos.
- `check-versions.sh` wird rot, sobald eine Stelle vergessen wurde — genau der Zweck; Rollback nicht nötig.
- Schreiben in `tasks/private/` aus einem Skript: nur Append und Commit, nie Push; bei fehlendem Repo nur
  Dateien.

## Doku-Impact

`docs/developer/cicd.html` DE+EN (zwei neue Abschnitte, Release-Checkliste um `check-versions.sh`),
`DEVELOPMENT.md` (heavy.sh, history.csv, Notify), `CHANGELOG.md` Unreleased, `.claude/rules/release.md`
(check-versions.sh vor dem Tag), `/test`-Skill. README unverändert.

## Offene Fragen (Design-Gate)

1. **Benachrichtigung:** `--notify` an eine ntfy-/Webhook-URL jetzt bauen (20 Zeilen, Default aus) oder erst mit
   Stufe 13? Empfehlung: jetzt, Default aus — du startest den Lauf abends und willst nicht nachsehen müssen.
2. **Gegenprobe-Logik:** Basis grün + HEAD rot ⇒ REG, Basis rot ⇒ extern (Kevin sichtet). Die Roadmap sagt
   „Gegenprobe rot ⇒ REG"; ich halte das für einen Formulierungsfehler. Bitte bestätigen.
3. **Zweite VM automatisch** bei drei identisch roten Läufen (Empfehlung; +40 min, nur im Kandidatenfall) oder
   nur mit Schalter?
4. **`--capstone` schließt `--enforce` ein** (R-0022). Empfehlung ja; der erste Lauf kann dadurch rot werden.
5. **MSI-Job** bleibt `continue-on-error` bis Stufe 12 (Empfehlung) oder wird mit der Install-Assertion hart?
6. **Upgrade-Pfad Schritt 4** (`update.sh` real gegen einen Vorgänger-Stack, braucht GitHub-Assets) jetzt oder
   nur die Compose-/Alembic-Migration (Schritte 1–3)? Empfehlung: beides, Schritt 4 dep-gated.
