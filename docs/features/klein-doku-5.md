<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-doku-5 — Spec

## Problem
- **R-1016:** Die Keyring-Prüfsätze in `docs/admin/agent-deployment.html` (Schritt 1, ca. Z. 85, und 1b, ca. Z. 99; EN
  `docs/en/admin/agent-deployment.html` Z. 86 und 99) nehmen mit `awk 'p {print $10; p=0} $1=="pub" {p=1}'` die Zeile
  *nach* `pub`, ohne ihren Typ zu prüfen. Trägt der Schlüssel einen designierten Widerrufer, steht dort ein
  `rvk`-Record statt `fpr`; der Satz liest dessen Feld 10 und bricht fälschlich mit „kein Schlüssel“ ab.
  `scripts/agent-install.sh` (`primary_fprs`) verlangt dagegen ausdrücklich `fpr`. Die Doku soll dasselbe tun. Die genaue
  Record-Folge wird beim Bau mit einem Wegwerf-Schlüssel samt Widerrufer in einem eigenen gpg-Homedir nachgestellt
  (nicht verifiziert bis dahin).
- **R-1018:** Die Doku des `restored`-Wächters (`docs/developer/webui.html` Z. 69, EN gleich, und der Docstring von
  `watchIdle` in `apps/web/src/lib/idle.ts` Z. 20–21) nennt nur den Fall „gespeicherte Zeit zu alt“. Der Code
  (`idle.ts` Z. 36–43) meldet auch ab, wenn die Zeit in der Zukunft liegt oder keine Zahl ist; nur eine fehlende Zeit
  (`null`) zählt als Bedienung.

## Ziel / Nicht-Ziele
Doku und Docstring geben das Verhalten vollständig wieder. Keine Verhaltensänderung, kein Eingriff in
`agent-install.sh`.

## Dateien
`docs/admin/agent-deployment.html`, `docs/en/admin/agent-deployment.html`, `docs/developer/webui.html`,
`docs/en/developer/webui.html`, `apps/web/src/lib/idle.ts` (nur Kommentar).

## Datenmodell / API / Integrationen
Keine. gpg-Colon-Format (`doc/DETAILS` im GnuPG-Repo) wird beim Bau gegen die lokale gpg-Ausgabe geprüft.

## Trade-offs
Der Prüfsatz kann `fpr` verlangen (wie `agent-install.sh`) oder rvk-Zeilen überspringen. Empfehlung: `fpr` verlangen, so
bleibt Doku = Installer, und ein unerwarteter Record scheitert sichtbar statt still.

## Risiken & Rollback
Gering; ein Copy-Paste-Rezept. Beim Bau mit Gegenprobe (Schlüssel mit und ohne Widerrufer) ausgeführt. Ein Commit je Task
zurücknehmbar.

## Doku-Impact
Die genannten Seiten DE+EN sind selbst der Inhalt.

## Offene Fragen
Keine.
