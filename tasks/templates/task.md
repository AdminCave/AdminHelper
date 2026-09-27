<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later

Vorlage für einen Task-Eintrag. `bash scripts/dev/ledger.sh new-task <ledger>
--title "…"` hängt alles UNTERHALB dieses Kommentars an das Ledger an und ersetzt
<ID> durch die nächste freie Task-Nummer und <Titel> durch den Titel.

Pflichtfelder sind die aus tasks/README.md. Die optionalen Zeilen der
Beweis-Konvention (tasks/README.md) setzt nur, wer sie belegen kann — eine
Vorlage, die Felder erzwingt, die niemand liest, erzieht dazu, Felder zu
erfinden. Deshalb stehen sie hier und nicht unten im Eintrag:

Beweis: <branch>@<sha> · <kommando> → <erwartete ausgabe>
Orakel: crash|contract|property|differential|mutation-sample|coverage|analyzer|metric
Refuter: <wer/was widerlegen wollte> → <ergebnis>
Dedup-Key: <klasse>:<komponente>:<datei>:<symbol>
Metrik: <werkzeug version>: <vorher> → <nachher>
Kosten: <zeit, läufe, tokens>
HEAD: <sha>
Semantik: <docs/…> — „<zitat>" (Pflicht bei /feature-plan --kurz)
-->
### <ID> — <Titel>  [ ]
Komponente: <komponente> · Dateien: <pfad…>
Änderung: <was genau geändert wird — eine fokussierte Änderung, keine Design-Entscheidung>
Verify: bash scripts/dev/verify.sh <komponente> --strict
Doku: <Datei(en), oder „keine (Grund)">
