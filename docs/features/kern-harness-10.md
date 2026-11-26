# Harness: heavy.sh-Klassifizierer und Audit-Abfrage (kern-harness-10)

Roadmap: R-0737, R-1126, R-1127, R-1284, R-1369, R-1421, R-1672 (dazu R-0121, R-1128, R-1133: auf main schon
behoben) · Kevin 2026-11-25: Harness-Fund angenommen (Durchsicht)

## Problem / Motivation
- **R-0737** `check_audit` (`scripts/tests/heavy.sh:1093`) fragt `audit.yml/runs?per_page=1` ohne Branch: der
  neueste Lauf irgendeines Branches bestimmt die Audit-Zeile des Reports und die REL-Zeile.
- **R-1369** Kopfkommentar `heavy.sh:14`: die Zeile `gui` steht eine Stelle zu weit links unter `rest`.
- **R-1284** Laeuft Teil gui auf voller Box (`no space left on device`, danach `tauri build failed`), zaehlt der Teil
  als `fail` (Lauf 2026-11-10-1027); die Box konnte den Schritt gar nicht laufen lassen.
- **R-1421** `first_marker` (`heavy.sh:707`) vergleicht Marker woertlich; ein Marker mit Zufallsport (`tcp-NNNNN`)
  wechselt je Retry, der Schritt wird `fail` statt Kandidat.
- **R-1672** `build_failed` (`heavy.sh:722`) greift bei jedem Treffer von `tauri build failed` im Log, auch bei
  Nicht-Desktop-Schritten und bei Meldungen eines Unit-Tests (`apps/desktop/e2e/test/unit/launcher.test.js:61`).
  Gemeint ist der wdio-Hook (`apps/desktop/e2e/wdio.conf.js:119`) eines Desktop-Spec-Schritts.
- **R-1126** `second_vm_check` stuft `extern` ein, wenn auch der Basis-Commit rot ist. Die zweite Box ist aber mit
  dem Bootstrap des Kopf-Commits gebaut (`warm.sh` aus dem w2-Worktree auf HEAD); aendert der Kopf
  `scripts/vm/bootstrap_linux.sh` (d9120d94, Node 26), ist die Basis-Gegenprobe keine (Sammellaeufe 2026-11-03 und
  -04: GUI 10x `extern`).
- **R-1127** Nach einem `extern` faehrt jeder weitere Kandidat mit derselben Fehlersignatur die volle Gegenprobe
  (Box, HEAD, Basis); am 2026-11-04 zehn GUI-Specs mit `UND_ERR_INVALID_ARG`, etwa 40 min ohne Erkenntnis.
- **R-0121, R-1128, R-1133** sind auf main behoben (f7b417cd4; R-1337 macht schemathesis zu `fund`; e36e45015).
  Sie fahren als `[~]`-Tasks mit, damit die Zeilen ueber diesen Zug schliessen.

## Ziel & Nicht-Ziele
- Ziel: der Report liest das Audit von main; volle Platte ist `infra`; Ports im Marker stoeren den Vergleich nicht;
  `build_failed` gilt nur am wdio-Hook eines Desktop-Spec-Schritts; `extern` nur, wenn die Basis mit ihrem eigenen
  Box-Bootstrap lief, sonst `unbestaetigt`; ein weiterer Kandidat mit derselben Fehlercode-Signatur wie ein
  `extern` dieses Laufs wird ohne zweite VM `extern`.
- Nicht-Ziel: Retries ueberspringen (R-1127 spart die zweite VM, nicht die drei Retries: die laufen, bevor ein
  `extern` feststeht); die Basis auf einer eigenen, mit ihrem Bootstrap gebauten Box fahren (R-1126 waere dann
  teuer: ein voller Bootstrap 10–20 min je Kandidat).

## Betroffene Komponenten & Dateien
`scripts/tests/heavy.sh`, `scripts/tests/heavy_test.sh`, `docs/developer/cicd.html` +
`docs/en/developer/cicd.html` (Klassen-Tabelle), `.claude/skills/test/SKILL.md` (Klassen-Tabelle).

## Datenmodell / API / Migrationen
Keine. Report und `history.csv` behalten ihre Form; neu sind nur Detail-Texte.

## Externe Integrationen
GitHub REST „List workflow runs for a workflow“ nimmt den Query-Parameter `branch`
(docs.github.com/en/rest/actions/workflow-runs#list-workflow-runs-for-a-workflow).

## Trade-offs & Alternativen
- **R-1126:** (a) Basis rot und `scripts/vm/bootstrap_linux.sh` unterscheidet sich zwischen Basis und HEAD →
  `unbestaetigt` mit Detail (Empfehlung: billig, ehrlich); (b) die Basis auf frisch gebauter Box — 10–20 min mehr je
  Kandidat.
- **R-1127:** Signatur = erster Node-Fehlercode im ersten Retry-Log (`UND_ERR_*`, `ERR_*` ohne `ERR_ASSERTION` und
  `ERR_TEST_FAILURE`; keine errno wie `ECONNREFUSED`, die hat zu viele Ursachen; `ok`-Zeilen zaehlen nicht). Marker taugen nicht: jede Spec meldet ihren eigenen (`FAIL connect GUI specs failed`, …); `WebDriverError`
  ist zu allgemein. Ohne Fehlercode bleibt die volle Gegenprobe. Risiko: eine echte Regression mit demselben Code im
  selben Lauf wird `extern` — sie bleibt rot im Report („Kevin sichtet“), sperrt Merges wie jedes `extern`, und das
  Detail nennt den Schritt, dessen Gegenprobe uebernommen wurde.
- **R-1672:** auf Desktop-Spec-Schritte (`desktop_e2e_*`, `desktop-e2e smoke`) und die Hook-Zeile
  `HookError [SevereServiceError]: tauri build failed` beschraenken.

## Risiken & Rollback
Fehlklassifizierung im Sammellauf (zu milde Klasse verdeckt eine Regression). Jede Aenderung bekommt in
`heavy_test.sh` einen Fall und eine Gegenprobe; Rollback per Revert der Task.

## Doku-Impact
`docs/developer/cicd.html` DE+EN und `.claude/skills/test/SKILL.md`: Klassen `infra`, `unbestaetigt`, `extern`.
Kein CHANGELOG (Harness, kein Nutzerverhalten).

## Offene Fragen
Keine aus Kevins Bereich; R-1126/R-1127 nach den Empfehlungen oben.
