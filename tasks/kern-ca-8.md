<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-ca-8 — Task-Ledger
Status: geplant · Branch: feature/kern-ca-8 · Review: pro Task
Spec: docs/features/kern-ca-8.md (Roadmap R-1112)
Heavy: scenario --tunnel — FRP-Tunnel-Datenpfad und PKI (frps-Leaf, frpc von Agent und Visitor über drei Hosts); ask-first
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Stand `origin/main@03c4068a`. Jede Task liegt auf einem Risikopfad (PKI, FRP): `security` je Task. T3 und T4 fahren als R-1121 in `tasks/kern-ca-9.md`.

### T1 — frps-Leaf trägt einen eigenen festen Namen (R-1112)  [ ]
Komponente: ca-issuer · Dateien: apps/ca-issuer/app/config.py, apps/ca-issuer/app/main.py, apps/ca-issuer/tests/test_frps_cert.py, apps/ca-issuer/tests/test_gateway_cert.py, apps/ca-issuer/tests/test_config.py
Änderung: `config.py` bekommt die Konstante `FRPS_TLS_NAME = "frps.adminhelper.invalid"`; `frps_extra_sans()` hängt sie an (einmal, auch wenn sie schon dasteht), andere Leafs tragen sie nicht (Entscheidungen im Code und unter Entscheidungen). Tests zuerst rot: das frps-Leaf trägt den Namen neben `DOMAIN` und den Extra-SANs; ein bestehendes frps-Leaf ohne ihn wird beim Start neu ausgestellt; kein anderes Leaf trägt ihn.
Verify: bash scripts/dev/verify.sh ca-issuer --strict -- tests/test_frps_cert.py tests/test_gateway_cert.py tests/test_config.py
Doku: → T5

### T2 — Agent setzt transport.tls.serverName in frpc.toml (R-1112)  [ ]
Komponente: agent · Dateien: apps/agent/internal/frpc/sync.go, apps/agent/internal/frpc/rewrite.go, apps/agent/internal/frpc/rewrite_test.go, apps/agent/internal/frpc/sync_flow_test.go
Änderung: Nach `checkServerConfig` (`sync.go:252`) setzt der Agent `serverName = "frps.adminhelper.invalid"` in den `[transport.tls]`-Block des Server-Texts (ohne Kopf als `transport.tls.serverName` im Root); `checkServerConfig` lehnt einen vom Server gesendeten `serverName` weiter ab, also steht der Schlüssel nie doppelt. Die Konstante nennt im Kommentar ihr Gegenstück (ca-issuer `config.py`). Tests zuerst rot: die geschriebene `frpc.toml` trägt den Namen genau einmal im TLS-Block, für den Text mit und ohne `[transport.tls]`-Kopf; der Hash-Vergleich mit dem Server (`FrpHashFile`) bleibt am Server-Text.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T5

### T5 — Doku und Changelog (R-1112)  [ ]
Komponente: scripts · Dateien: docs/admin/frp-tunnel.html, docs/en/admin/frp-tunnel.html, docs/developer/agent.html, docs/en/developer/agent.html, changelog.d/kern-ca-8.md
Änderung: `frp-tunnel.html` (Abschnitt Tunnel-PKI, `trustedCaFile`-Punkt): frpc prüft das frps-Zertifikat gegen `ca.crt` und den festen Namen `frps.adminhelper.invalid`, den nur das frps-Leaf trägt; `agent.html`: der Agent setzt ihn in `frpc.toml`. `changelog.d/kern-ca-8.md` unter `### Security`, ohne Details.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: docs/admin/frp-tunnel.html + EN · docs/developer/agent.html + EN · changelog.d/kern-ca-8.md
Task-Review: am Ende

## Entscheidungen
