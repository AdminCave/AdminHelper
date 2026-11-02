<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# ops-3 — Spec

Roadmap: R-0859, R-0862, R-0896, R-0865, R-0986, R-0956, R-0987 (Zug `tasks/ops-3.md`).

## Problem / Motivation
Nachzügler aus den Prüfungen von ops-install-hardening (#275), compose-hardening und update-rollback, alle in
`scripts/update.sh`, seinem Test und der Installations-Doku:
- **R-0862, R-0865:** Die Meldungen der `.env`-Prüfung (`check_env_templates`, `scripts/update.sh:194`) sind deutsch,
  neue CLI-Meldungen sollen englisch sein. Dazu geben sie mehr aus der `.env` wieder als nötig (Details privat).
- **R-0896:** `migrate_env` (`scripts/update.sh:675`) hält einen auskommentierten Schlüssel aus `.env.example` für
  vorhanden und ergänzt ihn nicht. `.env.example:93-95` verlangt aber für `CA_ROOT_PASSPHRASE`, dass die Zeile bleibt,
  sonst bricht `docker compose up` ab. Ein Kommentar im Rollback (`scripts/update.sh:729-730`) beschreibt
  `CA_ROOT_PASSPHRASE` als von `init-secrets.sh` immer gefüllt; das stimmt nicht mehr.
- **R-0986, R-0956:** Ein Signal während eines Rollbacks bricht ihn ab oder startet ihn neu: Nur `on_signal`
  (`scripts/update.sh:650`) setzt die Traps zurück, ein Rollback aus einem Fehlerpfad nicht. Mit `--no-rollback`
  nennt der Signalpfad den Standardtext auch dort, wo er nicht stimmt (während des Tauschs, nach `pin_images`).
- **R-0987:** `update_test.sh` (Abschnitt 45, `:1442`) prüft `rollback_after_deploy` nicht für „Datenbank migriert und
  Rollback unvollständig“ und nicht für „Stopp des Stacks scheitert“.
- **R-0859:** Die Installations-Doku (`docs/admin/installation.html:97`, EN `:78`) nennt `--admin-password-file`, sagt
  aber nicht, wie man die Datei ohne Shell-History anlegt und danach löscht.

## Ziel & Nicht-Ziele
Ziel: Jede Zeile ist behoben und, wo es Verhalten ist, durch einen Fall in `update_test.sh` belegt.

Nicht-Ziele:
- keine Warnung in `install.sh` bei einer lesbaren Passwortdatei (R-0859 nennt sie optional; `install.sh` bleibt
  unberührt);
- keine neue Rollback-Logik, nur die Signalbehandlung und die Texte.

## Betroffene Komponenten & Dateien
- `scripts/update.sh`
- `scripts/tests/update_test.sh`
- `docs/admin/installation.html` und `docs/en/admin/installation.html`
- `changelog.d/ops-3.md`

## Datenmodell / API / Migrationen
Keine. Sichtbar ändern sich die Meldungen von `update.sh` (englisch, `.env`-Prüfung nennt die Zeile statt des
Schlüssels) und, bei einem auskommentierten Pflichtschlüssel, eine neu angehängte Zeile in `.env`.

## Externe Integrationen
Keine. Das `.env`-Format von Docker Compose ist in `check_env_templates` schon nachgebaut und bleibt unverändert.

## Trade-offs & Alternativen
- **R-0862:** Nur die Zeilennummer zu nennen ist weniger bequem als der Schlüssel, gibt aber nichts aus der Datei
  wieder. Die Zeilennummer reicht zum Finden. Empfehlung: Zeilennummer.
- **R-0896:** Nur aktive Zeilen zählen. Ein Betreiber, der einen Pflichtschlüssel bewusst auskommentiert hat, bekommt
  ihn mit dem Wert aus `.env.example` zurück; ohne ihn bricht Compose ohnehin ab. Empfehlung: aktive Zeilen.
- **R-0986/R-0956:** Die Traps zu Beginn beider Rollback-Funktionen auf „ignorieren“ setzen. Ein Strg-C während der
  Rücknahme ist dann wirkungslos, statt sie halb abzubrechen. Empfehlung: ignorieren.

## Risiken & Rollback
Mittel: `update.sh` läuft bei jedem Betreiber-Update. Jede Task ist ein eigener Commit und einzeln per Revert
rücknehmbar. Der PR ändert `scripts/update.sh`, also merged Kevin (CLAUDE.md §2).

## Doku-Impact
- Installations-Doku DE und EN: das Anlegen der Passwortdatei.
- CHANGELOG-Fragment.
- Sonst keine.

## Offene Fragen
Keine.
