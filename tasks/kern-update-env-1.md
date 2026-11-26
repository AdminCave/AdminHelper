# .env-Prüfung für Compose ab v5.8.0 — Task-Ledger
Status: aktiv · Branch: feature/kern-update-env-1 · Review: am Ende
Spec: Roadmap R-1804
Heavy: none — nur die .env-Vorprüfung in update.sh/install.sh (kein Stack-, Gateway-, PKI- oder Datenpfad); der hermetische Differential-Test läuft gegen echtes docker compose, lokal zusätzlich gegen compose v5.8.0, und der nächtliche Sammellauf über main fährt ihn auf der Box mit v5.8.0
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Semantik: docs/admin/installation.html:177 — „Ebenso beenden ein nie geschlossenes Anführungszeichen und ein Schlüssel,
den Compose nicht annimmt, jeden docker compose-Aufruf […] update.sh prüft all das vor dem ersten Compose-Aufruf“
(EN docs/en/admin/installation.html:75). Compose ab v5.8.0 (compose-go v2.17.0, PR 970) nimmt keinen leeren Schlüssel
(`=wert`, „key cannot be empty“) mehr an und liest die letzte Zeile ohne Zeilenumbruch und ohne `=`/`:` als Schlüssel
wie jede andere (ein Leerzeichen darin: „key cannot contain a space“). Die Prüfung lässt beides durch; das Update
scheitert dann erst am ersten Compose-Aufruf.

### T1 — .env-Prüfung lehnt leeren Schlüssel und Leerzeichen im Schlüssel der letzten Zeile ab  [ ]
Komponente: scripts · Dateien: scripts/update.sh, scripts/install.sh, scripts/tests/update_test.sh, docs/admin/installation.html, docs/en/admin/installation.html, changelog.d/kern-update-env-1.md
Änderung: `check_env_templates` (Block „env check“, update.sh:295–296, install.sh:485–486 byteweise gleich) lehnt
einen leeren Schlüssel ab und behandelt die letzte Zeile ohne `=`/`:` wie jede andere Schlüsselzeile (Sonderfall
`spaced=$eol` entfällt). update_test: `=zz9v` (update_test.sh:1150) und der eof-Fall (update_test.sh:1200) erwarten
die Ablehnung; der Differential-Vergleich nimmt bei einem docker compose unter v5.8.0 für genau diese Fälle die
strengere Ablehnung der Prüfung hin (älteres Compose nimmt sie an), ab v5.8.0 gilt volle Übereinstimmung. Doku DE+EN:
Schlüssel nicht leer, die letzte Zeile gilt als Schlüssel.
Beweis: Sammellauf 2026-11-26 scripts (hermetic) · main@6fb273390 · `bash scripts/tests/update_test.sh` mit docker compose v5.8.0: `FAIL [=zz9v]: --check rc=0, docker compose config rc=1 (… line 11: key cannot be empty)` und `FAIL eof: --check rc=0, docker compose config rc=1`
Dedup-Key: bug:scripts:update.sh:env-empty-key
HEAD: 673575277
Verify: bash scripts/dev/verify.sh scripts --strict -- update_test install_test
Doku: docs/admin/installation.html, docs/en/admin/installation.html, changelog.d/kern-update-env-1.md

## Entscheidungen
- 2026-11-26: Die Testbox-Vorlage pinnt `docker-compose-plugin` nicht: der ungepinnte Stand hat diesen Nutzerfehler
  gefunden, Nutzer bekommen dieselbe Version. Kein Pin, keine Harness-Änderung.
- 2026-11-26: Strenger als ältere Compose-Versionen (sie nehmen `=wert` an): eine solche Zeile ist auch dort nutzlos
  (sie ergibt eine Variable ohne Namen, die nichts nutzen kann, compose-go PR 970) und bricht beim nächsten Compose-Update;
  die Meldung nennt die Zeile und den Weg (`#`).
