# ops-10 — Windows-Einzeiler `agent-install.ps1`

Roadmap: R-1578 (FEAT).

## Problem
Unter Windows lädt der Admin heute Agent und `frpc-windows-x86_64.exe` von Hand aus dem Release und ruft
`service install` (docs/admin/agent-deployment.html, Abschnitt „Windows“); das Provisionieren-Fenster bietet
für Windows keinen Installationsbefehl. Linux hat dafür `scripts/agent-install.sh`.

## Ziel & Nicht-Ziele
- Ziel: `scripts/agent-install.ps1` als Einzeiler für eine PowerShell als Administrator:
  `& ([scriptblock]::Create((irm https://raw.githubusercontent.com/AdminCave/AdminHelper/main/scripts/agent-install.ps1))) -Server https://… -ServerId <id> -CaFp <sha256>`.
  - Admin-Prüfung, fail-closed.
  - Neuestes Release (oder `-Version X.Y.Z`) von GitHub per HTTPS: `SHA256SUMS`,
    `adminhelper-agent-windows-x86_64.exe`, `frpc-windows-x86_64.exe` in ein eigenes Temp-Verzeichnis;
    beide Dateien gegen `SHA256SUMS` (Get-FileHash), Abweichung → Abbruch, bevor etwas installiert ist.
  - `service install` aus dem Temp-Verzeichnis (installiert und aktualisiert, frpc gegen den Pin des Agents).
  - Mit `-ServerId`: Token per `Read-Host -AsSecureString`, ohne `-Token` nie im Einzeiler, an
    `provision --token-stdin` über stdin; `-Token` für unbeaufsichtigte Rollouts.
- Nicht-Ziel: minisign unter Windows (Kevin 2026-11-19: nur HTTPS + SHA256SUMS); Installationsbefehl im
  Provisionieren-Fenster des Desktops (eigene Zeile); MSI.

## Betroffene Dateien
- `scripts/agent-install.ps1` (neu, SPDX)
- `scripts/tests/agent_install_ps1_test.sh` (neu, SPDX; hermetisch: Invarianten des Skripts), `scripts/tests/run.sh`
  (Eintrag in der Liste der Skript-Tests)
- `.github/workflows/ci.yml`: Job auf `windows-latest` (Admin), fährt das Skript gegen ein im Job gebautes Release
  über `http://127.0.0.1` (Override `AH_DL_BASE`/`AH_API_BASE` wie `agent-install.sh`, nur Loopback ohne TLS)
- `apps/server/tests/test_ci_workflow.py` (der Job läuft und überspringt sich nicht)
- `docs/admin/agent-deployment.html`, `docs/en/admin/agent-deployment.html`, `changelog.d/ops-10.md`

## Trade-offs
Vertrauensmodell schwächer als `agent-install.sh --from-github` (dort minisign): die Echtheit hängt an TLS zu
github.com; SHA256SUMS sichert nur die Übertragung. Kevin 2026-11-19 so entschieden; die Doku nennt es. Danach
prüft der Agent frpc ohnehin gegen seinen gepinnten Hash.

## Risiken & Rollback
Installer-Pfad. Beweis vor dem Merge: der Windows-CI-Job (Kevin 2026-11-19: zählt als scenario-Lauf; prüft
Install, Dienst läuft, Update, Ablehnung bei falschem Hash, `uninstall --purge`; keine echte Provisionierung).
Rollback: Revert; das Skript ist neu, nichts hängt daran.

## Doku-Impact
`docs/admin/agent-deployment.html` DE+EN, Abschnitt Windows: Einzeiler, Parameter, Vertrauensmodell;
CHANGELOG-Fragment.

## Offene Fragen
Keine (Kevin 2026-11-19: Bootstrap nur HTTPS + SHA256SUMS; CI-Job zählt als scenario-Lauf).
