<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later

Vorlage für einen Task-Eintrag. `bash scripts/dev/ledger.sh new-task <ledger>
--title "…"` hängt alles UNTERHALB dieses Kommentars an das Ledger an und ersetzt
<ID> durch die nächste freie Task-Nummer und <Titel> durch den Titel.

Pflichtfelder sind die aus tasks/README.md. Die fünf optionalen Zeilen am Ende
(Beweis/Orakel/Refuter/Dedup-Key/Metrik) gehören zu Stufe 5 und bleiben bis
dahin weg — eine Vorlage, die Felder erzwingt, die niemand liest, erzieht dazu,
Felder zu erfinden.
-->
### <ID> — <Titel>  [ ]
Komponente: <komponente> · Dateien: <pfad…>
Änderung: <was genau geändert wird — eine fokussierte Änderung, keine Design-Entscheidung>
Verify: bash scripts/dev/verify.sh <komponente> --strict
Doku: <Datei(en), oder „keine (Grund)">
