<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# arch-rdp-embedded — Task-Ledger
Status: aktiv · Branch: feature/arch-rdp-embedded · Review: pro Task
Spec: docs/features/arch-rdp-embedded.md (Roadmap R-1074)
Heavy: none — Machbarkeitsstudie, ändert nur Spec und Ledger; Prototypen laufen außerhalb des Baums (Spec „Prototypen“)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

## Tasks

### T1 — Kriterienmatrix aus der Doku und Prototyp-Auswahl (R-1074)  [x]
Komponente: scripts · Dateien: docs/features/arch-rdp-embedded.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @9ede2e22 2026-11-02T14:00:49+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Abschnitt „Ergebnis: Matrix“ in der Spec: V1, V2, V2b, V3a, V3b, V3c gegen K1–K15 aus offiziellen Quellen
(Repos, Crate-Doku, MS-Spezifikationen, Tauri-Doku), je Zelle Quelle oder „nicht verifiziert“; harte Ausschlüsse mit
Grund; welche Varianten T2–T4 prototypisch prüfen.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: keine (das Ergebnis ist die Spec selbst; kein Produktverhalten)
Task-Review: am Ende

### T2 — Protokoll-Prototyp gegen xrdp (R-1074)  [x]
Komponente: scripts · Dateien: docs/features/arch-rdp-embedded.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @ffa153a0 2026-11-02T15:18:32+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: xrdp im Docker-Container (nur Loopback), kopfloser IronRDP-Probe-Client in Rust unter
`.ah-out/arch-rdp-embedded/`; gemessen Codec, fps, Mbit/s, Dekodierzeit, CPU unter fester Bildlast, dazu Resize,
Zwischenablage, Laufwerk und Audio soweit xrdp sie anbietet; Gegenmessung FreeRDP 3 unter Xvfb. Abschnitt
„Ergebnis: xrdp“ mit Versionen, Kommandos, Zahlen.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: keine (das Ergebnis ist die Spec selbst; kein Produktverhalten)
Task-Review: am Ende
Abhängt von: T1

### T3 — Bildweg im Webview (R-1074)  [x]
Komponente: scripts · Dateien: docs/features/arch-rdp-embedded.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @fd00c4cc 2026-11-02T15:26:17+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Wegwerf-Tauri-2-App auf der Desktop-VM der Lane (Xvfb): synthetische Rechteck-Last 1920×1080 (10/50/100 %,
30/60 Hz) über Tauri-Channel (rohe Bytes) und lokalen WebSocket auf Canvas2D `putImageData` und WebGL
`texSubImage2D`; Durchsatz, Latenz, CPU, Tastatur-Fang; V1-WASM-Komponente, falls T1 sie nicht ausschließt.
Abschnitt „Ergebnis: Webview“.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: keine (das Ergebnis ist die Spec selbst; kein Produktverhalten)
Task-Review: am Ende
Abhängt von: T1

### T4 — Windows-Probe (R-1074)  [x]
Komponente: scripts · Dateien: docs/features/arch-rdp-embedded.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @3add73e1 2026-11-02T16:26:51+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Probe-Client aus T2 gegen einen echten Windows-Host: NLA/CredSSP, Codec-Aushandlung ohne AVC, Resize,
Zwischenablage, Audio, Laufwerke, Monitor-Layout. Abschnitt „Ergebnis: Windows“; ohne Host „nicht verifiziert“ mit
Grund. Keine Adressen, Hostnamen oder Zugangsdaten in der Spec.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: keine (das Ergebnis ist die Spec selbst; kein Produktverhalten)
Task-Review: am Ende
Abhängt von: T2

### T5 — Entscheidung und Bauplan für R-1075 (R-1074)  [ ]
Komponente: scripts · Dateien: docs/features/arch-rdp-embedded.md
Änderung: Abschnitt „Ergebnis: Entscheidung“: gewählte Variante mit Begründung und Restrisiken, Bauplan für R-1075
(Stufen und Tasks, Abhängigkeiten R-1069/R-1070, Heavy, Lizenzen und `THIRD_PARTY_LICENSES.md`, CSP und
Capabilities, Mockup-Funktionen je Stufe), offene Fragen an Kevin mit Empfehlung. Prototyp-Quellen und Rohdaten
nach `tasks/private/spikes/arch-rdp-embedded/`; R-1075 per `roadmap.py` mit Notiz auf `neu` zur Triage,
Folgezeilen als `neu`.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: keine (das Ergebnis ist die Spec selbst; kein Produktverhalten)
Task-Review: am Ende
Abhängt von: T2, T3

## Entscheidungen
- 2026-11-02: Prototyp-Code nicht im öffentlichen Baum (Wegwerf-Code ohne Prüfstufe); während der Studie unter
  `.ah-out/arch-rdp-embedded/`, am Ende Archiv unter `tasks/private/spikes/` (Spec „Prototypen“).
- 2026-11-02: Jede Task ändert nur die Spec und ist reine Doku (`Task-Review: am Ende`); die Abschlussprüfung prüft
  Inhalt und Belege.
- 2026-11-02 (Kevin): T4 nimmt als Windows-Host einen GitHub-Windows-Runner über einen temporären Workflow auf einem
  eigenen Wegwerf-Branch, der nie gemergt und danach gelöscht wird (Spec, Offene Fragen 1).
