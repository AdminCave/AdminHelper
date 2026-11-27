# klein-doku-12 — Doku- und Kommentar-Reste (R-1774, R-1802)

## Problem
- R-1774: `docs/developer/cicd.html:555` (EN :542) sagt "sobald scharf geschaltet", obwohl `release.yml` immer signiert und das Repo scharf ist (Zeile 609 sagt es selbst). `config.py:163` und `main.py:80` nennen `.bootstrap_token`, der Klartext-Token liegt aber in `.bootstrap_setup`. DE `installation.html:87` hat keinen STCP-Visitor-Hinweis, die EN-Seite (Zeile 42) schon.
- R-1802: die `release.yml`-Zeile der Workflow-Tabelle in `cicd.html` (DE+EN) nennt `image-pins`, `pkg-signing-key` und `freebsd-pkg-tool` nicht in der Jobliste; die curl-Regex in `test_every_download_of_the_release_retries` prüft die Flags je Zeile, ein mit Backslash umbrochener curl-Aufruf würde zu Unrecht rot, ein curl ohne Argument am Zeilenende bliebe unerkannt. Der Wortlaut des Nits steht nur im gelöschten Prüfer-Urteil; die Lesart hier ist aus dem Code abgeleitet (nicht verifiziert).

## Ziel & Nicht-Ziele
Nur die genannten Stellen. Kein Verhalten ändert sich; kein neuer Test außer der geschärften Regex samt Gegenprobe.

## Betroffene Dateien
`docs/developer/cicd.html`, `docs/en/developer/cicd.html`, `docs/admin/installation.html`, `apps/server/app/core/config.py`, `apps/server/app/main.py`, `apps/server/tests/test_ci_workflow.py`, `changelog.d/klein-doku-12.md`.

## Doku-Impact
Die Seiten oben, DE+EN; das Changelog-Fragment (englisch, umlautfrei).

## Risiken & Rollback
Kommentar- und Doku-Änderungen; die Testschärfung darf keinen heutigen curl-Aufruf rot färben (Lauf zeigt es). Revert je Task.

## Offene Fragen
Keine.
