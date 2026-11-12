# CI-Workflow: Stack-Job auf PRs, Pfad-Steuerung, Shards nach Laufzeit, merge_group, Nightly

Roadmap: R-1339, R-1340, R-1341, R-1342, R-1343 (Zug `tasks/arch-workflow-ci-1.md`; Kevin 2026-11-11 diktiert,
Merge durch Kevin, weil `.github/workflows/` sich ändert).

## Problem / Motivation

- **R-1339:** Der Job `integration-stack` (`.github/workflows/ci.yml:1239`, `if: github.event_name != 'pull_request'`)
  läuft auf PRs nicht; vor jedem Merge mit Stack-Bezug startet die Session deshalb einen eigenen Dispatch-Lauf desselben
  SHA (doppelte Arbeit). Der Kommentar `ci.yml:1235-1238` nennt die Bedingung zum Anheben („once we've lived a release
  round with it“); sie ist seit v0.46.0 erfüllt. Dazu laufen die Sammeljobs `server-result` (`ci.yml:149`) und
  `python-lock-server-result` (`ci.yml:371`) mit `if: always()`: ein überholter, abgebrochener Lauf meldet dort
  `failure` statt `cancelled`.
- **R-1340:** Jeder PR fährt die ganze Matrix: Server in py3.14 und py3.15 mit je zwei Shards, drei image-lock-Beine,
  Monitoring, CA-Issuer, schemathesis und beide Windows-Jobs, auch wenn der PR nur Web, Desktop oder Doku ändert. Die
  Server-Jobs belegen gut die Hälfte der Job-Minuten eines PR-Laufs; das Limit gleichzeitiger Jobs verlängert den
  kritischen Pfad.
- **R-1341:** `shard_of_each_file` (`apps/server/tests/conftest.py:523`) verteilt ganze Dateien nach Testanzahl. Shard 2
  läuft ~11 min, Shard 1 ~8 min; langsame Dateien (etwa `test_frps_supervisor.py`) zählen wie schnelle.
- **R-1342:** Eine Merge Queue (R-1344, Kevins Ruleset) braucht den Trigger `merge_group` im Workflow, sonst melden
  sich die Pflicht-Checks für die Queue nie.
- **R-1343:** schemathesis läuft in der PR-CI nur mit der expliziten Phase (`AH_SCHEMATHESIS_EXAMPLES=0`), tief
  (100 Beispiele) nur im lokalen Sammellauf; `backup_restore_test.sh` ebenfalls nur dort. Beide fanden dort echte
  Produktfehler.

## Ziel & Nicht-Ziele

Ziel:
- Stack-Job auf jedem PR; Sammeljobs mit `${{ !cancelled() }}`.
- PR-Läufe schlank: ein Job `changes` bestimmt aus dem Diff, welche Suiten Bezug haben; ohne Bezug wird ein Job per
  `if:` übersprungen (meldet „Success“). Server auf PRs nur py3.14; image-lock-Beine nur bei Lock- oder
  Dockerfile-Änderung. `push` auf `main`, `merge_group` und `workflow_dispatch` fahren immer alles.
- Shards nach gemessener Laufzeit (eingecheckte Tabelle), Fallback Testanzahl; der Manifest-Abgleich bleibt.
- `merge_group` als Trigger in `ci.yml` (ohne aktive Queue wirkungslos).
- Neuer Workflow `nightly.yml`: schemathesis mit 100 Beispielen und `backup_restore_test.sh` auf GitHub-Runnern,
  nachts, per Dispatch und auf PRs, die `nightly.yml` selbst ändern (das ist die Probe).

Nicht-Ziele:
- Merge Queue im Ruleset aktivieren (R-1344, Kevin) und Skill/CLAUDE.md dafür (R-1345).
- Änderungen am lokalen Sammellauf (`scripts/tests/heavy.sh`, `nightly.sh`, Skills; Harness).
- Pflicht-Checks im Ruleset ändern: alle 21 Namen bleiben.
- Weitere Jobs pfadsteuern (Agent-Linux, Desktop-UI, Web, Rust-Linux, Docker-Builds, Ops scripts bleiben immer an).
- Ein wechselnder schemathesis-Seed (siehe Trade-offs).

## Betroffene Komponenten & Dateien

- `.github/workflows/ci.yml`: Trigger, `server`/`server-result`, `python-lock-*`, `monitoring`, `ca-issuer`,
  `schemathesis`, `agent-windows`, `rust-windows`, `integration-stack`, neuer Job `changes`.
- `.github/workflows/nightly.yml` (neu).
- `.github/scripts/ci_changes.py` (neu, nur stdlib): Pfad → Suiten, Ausgabe für `$GITHUB_OUTPUT`.
- `apps/server/tests/test_ci_shards.py` (Sammeljobs), `apps/server/tests/test_ci_workflow.py` (neu: Trigger,
  Stack-Job, `nightly.yml`), `apps/server/tests/test_ci_changes.py` (neu: Klassifizierer und Pfadtabelle).
- `apps/server/tests/conftest.py`, `apps/server/tests/test_shard.py`, `apps/server/tests/shard_weights.toml` (neu).
- Doku: `docs/developer/cicd.html`, `docs/en/developer/cicd.html`, `changelog.d/arch-workflow-ci-1.md`.

Die Workflow-Tests liegen in der Server-Suite wie `test_ci_shards.py` und `test_release_images.py` heute: `verify.sh
scripts` fährt `.github/scripts/*_test.sh` nicht (R-1352), die Server-Suite schon, und jede Änderung unter `.github/`
löst über die Pfadtabelle alle Suiten aus.

## Datenmodell / API / Migrationen

Keine. Kein Produktcode, keine Vertragsdatei.

## Externe Integrationen (GitHub Actions, offizielle Doku, gelesen 2026-11-12)

- [Context availability](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts):
  `jobs.<job_id>.strategy` und `jobs.<job_id>.if` haben `github, needs, vars, inputs`; `jobs.<job_id>.env` zusätzlich
  `strategy, matrix`. Die Server-Matrix kann also aus `needs.changes.outputs` kommen.
- [Troubleshooting required status checks](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/collaborating-on-repositories-with-code-quality-features/troubleshooting-required-status-checks):
  „A job is skipped by a conditional“ → „The job reports "Success"“; ein per `paths` übersprungener Workflow lässt
  Pflicht-Checks auf „Pending“. Deshalb Steuerung per Job-`if:`, nie per `paths` in `ci.yml`.
- Name eines übersprungenen Matrix-Jobs: in der Doku **nicht verifiziert**. Darum bleibt `server-result` eine feste
  Matrix aus 3.14 und 3.15, die immer läuft und für ein nicht gewolltes Bein grün endet; die Pflicht-Checks
  „Server (pytest, py3.14)“ und „Server (pytest, py3.15)“ entstehen so in jedem Lauf mit ihrem Namen.
- [Managing a merge queue](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue):
  „You **must** use the `merge_group` event to trigger your GitHub Actions workflow when a pull request is added to a
  merge queue.“ `merge_group` kennt laut Workflow-Syntax nur `branches`, keine `paths`; `GITHUB_SHA` ist der
  Merge-Group-Commit. Die Payload-Felder `base_sha`/`head_sha` stehen nicht auf der Doku-Seite: nicht benutzt.
- [Expressions, Status check functions](https://docs.github.com/en/actions/reference/workflows-and-actions/expressions):
  `always()` „returns `true`, even when canceled“; empfohlen `if: ${{ !cancelled() }}`.
- [Events, schedule/workflow_dispatch](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows):
  beide nur aus dem Default-Branch; „In a public repository, scheduled workflows are automatically disabled when no
  repository activity has occurred in 60 days.“ Die Probe von `nightly.yml` vor dem Merge geht daher nur über
  `pull_request` mit `paths` auf die Datei selbst (ein eigener Workflow, kein Pflicht-Check).

## Entwurf

**Pfad-Steuerung (R-1340).** Job `changes` (checkout mit voller Historie, Python ohne Abhängigkeiten) ruft
`.github/scripts/ci_changes.py` auf. Auf `pull_request` liest es `git diff --name-only origin/$BASE_REF...$SHA`, sonst
setzt es jede Ausgabe auf „läuft“. Ausgaben: `server`, `server-legs` (JSON-Liste), `monitoring`, `ca-issuer`,
`schemathesis`, `lock-server`, `lock-monitoring`, `lock-ca-issuer`, `agent-windows`, `rust-windows`.
- Tabelle: enge Bereiche mit ihren Suiten (etwa `apps/web/**` → keine Python-Suite außer den Dateien, die die
  Server-Tests lesen; `apps/desktop/src-tauri/**` → `rust-windows`; `apps/agent/**` → `agent-windows`). Was die Suiten
  außerhalb ihrer Komponente lesen, steht ausdrücklich in ihrem Bezug (heute etwa `apps/web/src/lib/**`,
  `apps/desktop/src-tauri/src/tunnel.rs`, `docs/examples/**`, die vier API-/Monitoring-Seiten unter `docs/`, die von
  `apps/frps/Dockerfile.dockerignore` zugelassenen Agent-Dateien, die UI-Modelle, die die Monitoring-Tests lesen).
- **Fail-safe:** Ein Pfad außerhalb aller engen Bereiche (Wurzeldateien, `.github/**`, `scripts/**`,
  `docker-compose*.yml`, alles Unbekannte) schaltet alles ein. Scheitert `changes`, laufen alle gesteuerten Jobs:
  ihr `if:` lautet `${{ !cancelled() && needs.changes.outputs.<x> != 'false' }}`, die Matrix
  `fromJSON(needs.changes.outputs.server-legs || '["3.14","3.15"]')`.
- `server` wird bei `server-legs == '[]'` übersprungen (eine leere Matrix ist ein Fehler). `server-result` läuft
  immer (`!cancelled()`), feste Matrix; je Bein `WANT` aus `contains(...)`: nicht gewollt → grün mit Notiz, gewollt →
  wie heute Erfolg aller Shards und gleiche Manifeste.
- `--durations=25` im Server-Pytest; die JUnit-XML des 3.14-Beins wird Artefakt (Quelle der Laufzeittabelle).
- Gate-Test `test_ci_changes.py`: Wahrheitstabelle; jede getrackte Datei klassifiziert ohne Fehler; jede Datei unter
  `apps/` gehört zu mindestens einem Job; die dockerignore-Positivliste von `apps/frps` liegt im Server-Bezug; ein
  statischer Abgleich: Pfad-Literale außerhalb der eigenen Komponente in `apps/{server,monitoring,ca-issuer}/tests`
  (Formen `"apps/…"` und `/ "apps" / "…"`) liegen im Bezug ihrer Suite. Der Abgleich ist eine Heuristik; was er nicht
  sieht, fängt der volle Lauf auf `main` (Revert-Regel), mit R-1344 die Queue vor dem Merge.

**Shards nach Laufzeit (R-1341).** `apps/server/tests/shard_weights.toml` trägt je Testdatei Sekunden und Testanzahl
aus einer JUnit-XML des 3.14-Beins (Artefakt aus T3); Gewicht einer Datei = Sekunden je Test × Anzahl der nach `-m`/`-k`
gesammelten Tests; unbekannte Dateien bekommen den Mittelwert je Test. Ein Befehl im Kopf der Datei erzeugt sie neu.
Der Manifest-Abgleich bleibt unverändert.

**merge_group (R-1342).** Trigger `merge_group:`; `concurrency` bleibt (Queue-Refs sind eindeutig, abgebrochen werden
nur `pull_request`-Läufe); `public-repo-guard` liest bei `merge_group` den Bereich `origin/main...$SHA` (heute der
`*`-Zweig, künftig ausdrücklich benannt); `changes` fährt bei `merge_group` alles.

**Nightly (R-1343).** `.github/workflows/nightly.yml`: `schedule` (nachts), `workflow_dispatch`, `pull_request` mit
`paths: [.github/workflows/nightly.yml]`. Job 1: schemathesis wie der CI-Job, aber `AH_SCHEMATHESIS_EXAMPLES=100`; der
Lauf schreibt Commit und Beispielzahl in die Job-Summary. Job 2: `bash scripts/tests/backup_restore_test.sh` im
Compose-Stack wie `integration-stack`; ein SKIP (Exit 75) ist rot.

## Trade-offs & Alternativen

- **Pfad-Steuerung per `if:` statt `paths`** (empfohlen): `paths` lässt Pflicht-Checks hängen. Fremd-Actions wie
  `dorny/paths-filter` scheiden aus (Analyse V3: eigenes Skript, keine Fremd-Action; Lieferkette).
- **Enge Bereiche mit Fail-safe** statt „jede Datei hat eine exakte Suite-Liste“: weniger Gewinn bei Wurzel- und
  Skriptänderungen, dafür überspringt ein unbekannter Pfad nie etwas.
- **Fester schemathesis-Seed:** `derandomize=True` in den drei Suiten hält den Seed je Test fest; der
  Reproduktionsschlüssel ist Commit + Beispielzahl, den die Job-Summary nennt. Ein wechselnder Seed bräuchte
  Änderungen an drei Suiten und liegt nicht in der Zeile.
- **Tabelle aus CI-Zeiten** statt lokaler Messung: die Runner haben andere Kerne und ziehen Images; die lokale
  Messung ist der Fallback, falls das Artefakt fehlt.

## Risiken & Rollback

- Eine falsche Pfadtabelle überspringt eine Suite auf einem PR; der volle Lauf auf `main` fängt das (Revert-Regel).
  Rollback: die `if:`-Bedingungen entfernen.
- py3.15- und lock-only-Fehler fallen erst auf `main` auf (Analyse: in zehn Wochen keiner); Kevins Trade-off.
- Der Stack-Job verlängert keinen kritischen Pfad (~6 min parallel), kann aber auf PRs wackeln: ein Wackler wird
  Roadmap-Zeile, kein Rerun-Automatismus.
- `backup_restore_test.sh` auf GitHub-Runnern ist **nicht verifiziert**; die Probe ist der PR-Lauf von
  `nightly.yml`. Scheitert sie an der Umgebung, nicht am Produkt, fährt der Job nicht mit (Frage an Kevin).
- `nightly.yml` schaltet sich nach 60 Tagen ohne Repo-Aktivität ab (Doku); bei diesem Repo kein praktisches Risiko.

## Doku-Impact

`docs/developer/cicd.html` und `docs/en/developer/cicd.html`: Jobs auf PRs vs. `main`/`merge_group`, Pfad-Steuerung
und ihr Fail-safe, Stack-Job auf PRs, Shards nach Laufzeit (Tabelle neu erzeugen), `nightly.yml`. CHANGELOG-Fragment
`changelog.d/arch-workflow-ci-1.md` (Changed, Entwickler-Infrastruktur). Kein Nutzerverhalten.

## Offene Fragen

Keine vor dem Bau. Zwei Punkte nach dem Bau: Kevin merged (Workflow-Dateien); und falls die Probe zeigt, dass
`backup_restore` auf GitHub-Runnern nicht laufen kann, ob der Job entfällt.
