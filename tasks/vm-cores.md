<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# VM-Rollen: mehr vCPUs fuer Build-lastige Rollen — Task-Ledger (Kurz)
Status: erledigt (1/1) · Branch: fix/vm-cores · Commit-Granularität: pro Task · Review: am Ende (feature-review) · Modell: Fable (interaktiv, Kevins Auftrag 2026-09-18)
Spec: docs/features/harness-stufe-2.md (profiles.json) — Kurz-Ledger, keine eigene Spec
Fast-Suite: lokal · Warm-Profil: desktop
Heavy: keine; Wirkung misst der naechste Bake (`bake.sh linux-full`, bisher 56 min) und der naechste `heavy.sh all` (bisher 43 min)
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung
Roadmap: — (Kevin 2026-09-18: „vergebe zukuenftig mehr CPU-Kerne") · Hängt ab von: —
Befund: Host Xeon E5-2609 v3, 12 Kerne, waehrend des Capstones 2026-09-18 bei 9–11 % CPU, iowait 0,1–0,3 %, Load ~1; Bake `linux-full` 56 min auf 2 vCPUs, `heavy.sh all` 43 min auf 4 vCPUs. Die Kerne werden pro Klon aus `profiles.json` gesetzt, das Template spielt keine Rolle.

### T1 — profiles.json: desktop 6, bake 6, server 4  [x] (Test-Erwartung fuer die Server-Rolle nachgezogen; 230 vm.py-Tests gruen)
Komponente: scripts · Dateien: scripts/vm/profiles.json, scripts/vm/tests/test_vm.py
Änderung: Desktop 4 → 6 (Tauri/npm/cargo im `all`-Layer und in der Warm-Box), Bake 2 → 6 (Kompilieren beim Baken), Server 2 → 4 (Compose-Stack mit Postgres, Redis, VictoriaMetrics, Gateway). Rest bleibt bei 2. Ueberbuchung im Capstone: 4+6+5×2 = 20 vCPUs auf 12 Kernen — unkritisch, der Host war praktisch idle.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: CHANGELOG Unreleased/Changed
