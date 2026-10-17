<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# HTTPS-Tunnel-Mappings ohne STCP-Visitor — Task-Ledger
Status: aktiv · Branch: feature/desktop-https-mappings · Review: am Ende
Spec: Roadmap R-0432
Heavy: linux-full — Desktop-Tunnel-Store (Desktop-Journey im Sammellauf, `run.sh e2e`); keine neue Live-Spec: die HTTPS-Auflösung selbst (`resolve_connection`) bleibt unverändert, die Store-Logik belegt Vitest
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Hängt ab von: R-0402 (desktop-tunnel-refresh, aktiv in der anderen Session; tunnel.ts/tunnel.rs/frpc.rs werden dort umgebaut — Zeilenangaben vor dem Bau frisch greppen). Erst nach dessen Merge bauen; der Fix sitzt im Abgleich-Pfad, den R-0402 T6 einführt.

### T1 — Tunnel-Store lädt die Mappings auch ohne STCP-Visitor  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/stores/tunnel.ts, apps/desktop/ui/src/lib/stores/tunnel.test.ts, docs/developer/desktop.html, docs/en/developer/desktop.html, CHANGELOG.md
Änderung: Liefert der Abgleich `stopped` (Visitor-Bundle 404 = der Nutzer sieht keinen STCP-Tunnel), stoppt das nur frpc: der Store lädt die Mappings trotzdem über `bridge.fetchTunnels` und setzt sie, die Anzeige bleibt „idle“ ohne Fehlermeldung; scheitert `fetchTunnels`, bleiben die bisherigen Mappings (wie im übrigen Abgleich-Pfad von R-0402 T6). Nur ein Logout oder Moduswechsel (`stop()`) leert die Mappings. Vitest mit Fake-Bridge, zuerst rot: `refreshTunnel` → `stopped`, `fetchTunnels` → eine HTTPS-Mapping-Zeile → `getMappings()` enthält sie, keine Meldung; `stopped` und `fetchTunnels` wirft → Mappings unverändert, keine Meldung; `stop()` leert weiter. Doku DE+EN: im Absatz „Tunnel-Auflösung“ (`desktop.html:147`) ein Halbsatz, dass die Mappings auch ohne STCP-Tunnel geladen werden. CHANGELOG unter Fixed.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/stores/tunnel.test.ts
Doku: docs/developer/desktop.html + docs/en/developer/desktop.html (`:147`) · CHANGELOG.md (Fixed)
Beweis: origin/main@0f43781a `apps/desktop/ui/src/lib/stores/tunnel.ts:45-58` — `startTunnel` wirft bei 404 vom Visitor-Bundle, der catch setzt `mappings: []`; feature/desktop-tunnel-refresh (T6 im Bau, WT-Stand) `tunnel.ts` ~:124-125 — `refresh.outcome === 'stopped'` setzt `mappings: []`; `apps/desktop/src-tauri/src/tunnel.rs:77-85` löst HTTPS-Tunnel nur über diese Mappings auf
Dedup-Key: bug:desktop:tunnel.ts:https-mappings-without-stcp
HEAD: 0f43781a
Semantik: docs/developer/desktop.html:147 — „fetch_tunnels holt die Mappings von /api/frp/tunnels, resolve_connection rewritet passende Connections: stcp → host = 127.0.0.1, port = visitor_port (…), https → url = https://<custom-domain>.“ (keine Abhängigkeit vom Visitor-Bundle)
