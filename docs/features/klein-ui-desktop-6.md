<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-ui-desktop-6

## Problem / Motivation
R-1592 (Nutzermeldung 2026-11-18): Favicon/Logo in der Taskleiste des Admin-Clients stimmt nicht. Befund: Die
App-Icons (`apps/desktop/src-tauri/icons/*`, Fenster-Icon in `src-tauri/src/main.rs` über `icons/icon.png`) und
`docs/assets/logo.svg` sind noch das blaue Verlaufs-„A“. UI, Login und Favicon (`apps/desktop/ui/public/logo.svg`)
zeigen seit T13 des Design-Umbaus (122ca2dc5) die AdminCave-Marke. Die Taskleiste zeigt also ein anderes Zeichen
als die App selbst. Kevin hat am Gate entschieden (2026-11-19): die AdminCave-Marke gilt auch fürs App-Icon.

## Ziel & Nicht-Ziele
Ziel: Taskleiste, Fenster, Installer und Docs-Logo zeigen die AdminCave-Marke. Nicht-Ziele: die Marke selbst
ändern, Web-Favicon (zeigt sie schon), die Mobile-Icons (`icons/android`, `icons/ios`; kein Mobile-Build im Repo).

## Betroffene Komponenten & Dateien
`apps/desktop/src-tauri/icons/*` (png, ico, icns, Square*Logo), neue Quelle
`apps/desktop/src-tauri/icons/source.svg`, `docs/assets/logo.svg`. Kein Produktcode.

## Datenmodell / API / Migrationen
Keine.

## Externe Integrationen
Keine. Die Icons entstehen lokal mit ImageMagick aus `source.svg` (4096-px-Master, Lanczos): ein echtes
`icon.icns` (ic07–ic10) und ein `icon.ico` mit 16–256 px. Die Tauri-CLI (`tauri icon`) ist keine Voraussetzung.

## Trade-offs & Alternativen
Das Marken-SVG hat ein transparentes Glyph in einem Rundquadrat, das auf dunkler Taskleiste unsichtbar wird.
Empfehlung und Plan: die Quelle setzt das Rundquadrat in `#16181c` und das Glyph in `#ededee` (die beiden Farben
der Marke für hell/dunkel), damit das Icon auf jedem Hintergrund lesbar bleibt. Alternative (nur transparent
rendern) verworfen.

## Risiken & Rollback
Binäre Assets: Rollback per Revert. Ein kaputtes Icon bricht `tauri build`/`tauri-build` (validiert die Dateien);
`cargo test` fährt das mit. Aussehen unter Windows/macOS ist auf dieser Dev-Box nicht prüfbar (kein Display):
„nicht verifiziert“, das Linux-Icon prüft ein Blick auf das erzeugte PNG.

## Doku-Impact
`docs/assets/logo.svg` ist das Logo der Doku-Seiten (DE+EN verweisen auf dieselbe Datei): eine Datei, keine
Textänderung. CHANGELOG über `changelog.d/klein-ui-desktop-6.md`.

## Offene Fragen
Keine (App-Icon-Zeichen von Kevin entschieden).
