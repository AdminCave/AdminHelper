# STCP-Tunnel mit Protokoll web: Schema und Pfad — Task-Ledger
Status: bereit · Branch: feature/kern-frp-8 · Review: pro Task
Spec: docs/features/kern-frp-8.md (Roadmap R-1540)
Heavy: linux-full — Server-API (`/api/frp/tunnels`) ändert sich; FRP-Konfiguration, Visitor-Bundle und Datenpfad bleiben, kein Cross-Host-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1540 B+C: Auto-Verbindung mit Schema und Pfad, Nachziehen beim Protokollwechsel  [x]
Komponente: server · Dateien: apps/server/app/modules/frp/schemas.py, apps/server/app/modules/frp/_helpers.py, apps/server/app/modules/frp/tunnel_router.py, apps/server/tests/test_frp_auto_connection.py, apps/server/tests/openapi.snapshot.json, docs/developer/api-reference.html, docs/en/developer/api-reference.html
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @3679444a6 2026-11-18T19:45:35+01:00
Review: approve (.ah-out/review/kern-frp-8/T1.verdict.json)
Änderung: `FrpTunnelCreate`/`FrpTunnelUpdate` nehmen `auto_connection_scheme` (`http|https`) und `auto_connection_path` (beginnt mit `/`, ≤ 255, kein Leerraum, Steuerzeichen oder `#`; 422 sonst). `create_auto_connection` legt bei STCP und `web` die URL `<schema>://127.0.0.1:<Visitor-Port><pfad>` an (Vorgabe `http`), ohne Benutzername. `update_tunnel` zieht bei geändertem `protocol` oder `tunnel_type` die verknüpfte Verbindung mit (Typ; STCP: Host `127.0.0.1`, Port = Visitor-Port; `web`: URL mit Schema aus Request, alter URL oder `http`; sonst URL leer), auch eine von Hand verknüpfte. Neue Testdatei (SPDX): Anlegen mit und ohne Schema/Pfad, ungültiger Pfad 422, Wechsel ssh→web→rdp, von Hand verknüpfte Verbindung, älterer Client ohne die Felder.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_auto_connection.py tests/test_frp_tunnels.py tests/test_openapi_snapshot.py
Doku: docs/developer/api-reference.html, docs/en/developer/api-reference.html (neue Felder); Verhalten → T4

### T2 — R-1540 A: Desktop ersetzt beim Auflösen nur Host und Port  [x]
Komponente: desktop · Dateien: apps/desktop/src-tauri/src/tunnel.rs
Evidenz: run.sh[quick] desktop: 3 passed, 0 failed, 15 skipped @6d1e6bdf2 2026-11-18T19:53:53+01:00
Review: approve (.ah-out/review/kern-frp-8/T2.verdict.json)
Änderung: `to_visitor` setzt bei einer Web-Verbindung mit parsebarer URL nur Host `127.0.0.1` und Port `<lokaler Port>` (`url::Url::set_host`/`set_port`); Schema, Pfad und Query bleiben. Ohne oder mit unlesbarer URL wie heute `http://127.0.0.1:<Port>`. Gilt für Mapping und Literal-Visitor. Tests im Modul: https mit Pfad und Query, http ohne URL, `localhost`-URL, unlesbare URL.
Verify: bash scripts/dev/verify.sh desktop --strict
Doku: → T4

### T3 — R-1540 A+B: Tunnel-Dialog fragt Schema und Pfad, Inspektor zeigt die aufgelöste Adresse  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/infra/TunnelModal.svelte, apps/desktop/ui/src/components/infra/TunnelModal.test.ts, apps/desktop/ui/src/lib/models/frpTunnel.ts, apps/desktop/ui/src/lib/models/frpTunnel.test.ts, apps/desktop/ui/src/lib/api/types.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/components/connections/ConnectionInspector.svelte, apps/desktop/ui/src/components/connections/ConnectionInspector.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @cc77b6d18 2026-11-18T20:11:57+01:00
Review: approve (.ah-out/review/kern-frp-8/T3.verdict.json)
Änderung: Bei Protokoll `web` zeigt der Dialog statt des Benutzernamens Schema (`http|https`, Vorgabe `https` bei Zielport 443/8006/8443/9443, folgt dem Port, bis der Nutzer es selbst wählt) und optional einen Pfad; die Payload schickt `auto_connection_scheme`/`auto_connection_path`, bei anderen Protokollen nicht. Beim Protokollwechsel einer bestehenden Verbindung schickt der Dialog das Schema mit. Der Inspektor zeigt bei einer Verbindung mit Tunnel die aufgelöste Adresse (`bridge.resolveConnection`), nur wenn sie sich vom gespeicherten Ziel unterscheidet.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/infra/TunnelModal.test.ts src/lib/models/frpTunnel.test.ts src/components/connections/ConnectionInspector.test.ts
Doku: → T4
Abhängt von: T1

### T4 — R-1540: Doku Tunnel-Verbindung mit Schema und Pfad  [x]
Komponente: scripts · Dateien: docs/admin/frp-tunnel.html, docs/en/admin/frp-tunnel.html, changelog.d/kern-frp-8.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @a7b0b6a30 2026-11-18T20:14:43+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Abschnitt zum Visitor-Port und zur automatischen Verbindung: bei `web` Schema und Pfad statt Benutzername, Auflösung ersetzt nur Host und Port, Nachziehen beim Protokoll- oder Typwechsel, Hinweis auf die Zertifikatswarnung des Browsers bei `https`. CHANGELOG-Fragment.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/admin/frp-tunnel.html, docs/en/admin/frp-tunnel.html, changelog.d/kern-frp-8.md
Task-Review: am Ende
Abhängt von: T1, T2, T3

### T5 — R-1540: Entwickler-Doku und README zur Auflösung nachziehen (Abschlussprüfung)  [x]
Komponente: scripts · Dateien: docs/developer/desktop.html, docs/en/developer/desktop.html, README.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @f61dd9d2e 2026-11-18T20:35:06+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: „Tunnel-Auflösung“ (desktop.html DE+EN) und README nannten für Web über STCP noch `url = http://127.0.0.1:<port>`; jetzt: nur Host und Port der URL werden ersetzt, `http://127.0.0.1:<port>` nur ohne lesbare URL.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/developer/desktop.html, docs/en/developer/desktop.html, README.md
Task-Review: am Ende

## Entscheidungen
- 2026-11-18 Plan: Der Vertrauens-Schalter aus dem Titel der Zeile entfällt. Web-Verbindungen öffnen im Standard-Browser, `trust_cert` wirkt nur bei RDP (Spec, Nicht-Ziele).
- 2026-11-18 Plan: `types.ts` und `dictionaries.ts` ändert auch `feature/kern-provision-1` (dieselbe Session, andere Stellen), dessen T10 auch `developer/api-reference.html` (andere Route). T3 baut erst nach dessen Merge oder mergt `origin/main` vorher hinein.
- 2026-11-18 T3: Gebaut vor dem Merge von kern-provision-1 (wartet auf #569). Dessen Hunks in `types.ts` (ab Zeile 227) und `dictionaries.ts` (59–84, 1618–1643) liegen weit von denen dieser Task (187; 123/136/1421/1682/1695/2973); der spätere Merge löst sie textuell.
- 2026-11-18 T3: Schema und Pfad fragt und schickt der Dialog nur, wenn der Server sie auswertet (neuer Tunnel oder geänderte Form, `asksWebTarget`); bei unveränderter Form ignoriert sie der Server. Die Pfadregel des Servers prüft der Dialog vorab.
