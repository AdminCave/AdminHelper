<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Phase A — Detaillierter Task-Plan (Umsetzung der PKI/mTLS-Grundlage)

- **Status:** Bauplan (noch kein Code)
- **Datum:** 2026-06-11
- **Basis:** [ADR 0001](0001-unified-pki-and-secure-deployment.md) (D1–D11), alle Verifikationspunkte geklärt.

## Leitprinzip: permissive → enforced

`:443` darf **erst** auf `CERT_REQUIRED` umgelegt werden, wenn alle Client-Typen sich
enrollen und Certs vorweisen können. Bis dahin läuft das Gateway im **permissive**-Modus
(`CERT_OPTIONAL`, App-Authz nur loggend) — das System bleibt durchgängig nutzbar, der
„Scharfschalt"-Moment ist genau **ein** Task (A8) mit getestetem Rollback. Reihenfolge =
Abhängigkeitsreihenfolge.

```
A0 Spikes ─► A1 ca-issuer ─► A2 Gateway ─► A3 Per-Route-Authz(permissive) ─┐
                                │                                          │
                                ├─► A4 Agent-Enrollment ───────────────────┤
                                ├─► A5 Desktop-Enrollment ─────────────────┤
                                ├─► A7 frps unter tunnel-Intermediate ─────┤
                                └─► A6 Browser/Extension ──────────────────┤
                                                                           ▼
                          A9 Backup/Restore (parallel ab A1)        A8 ENFORCE (CERT_REQUIRED)
                                                                           │
                                                                    A10 Doku + ADR-Status
```

---

## Tasks

### A0 — Verifikations-Spikes (Restunsicherheiten schließen) ✅ ABGESCHLOSSEN 2026-06-11
- **Beschreibung:** Zwei Wegwerf-Spikes, die die zwei riskantesten Mechanismen *vor* dem
  echten Bau beweisen: (1) nginx mTLS-Terminierung → verifizierte Identität als Header an
  einen Upstream, der ihn echot; (2) frps verifiziert ein Client-Cert, das von einem
  **Intermediate** signiert ist (CA-Datei = Kette).
- **Betroffen:** throwaway compose + minimal nginx.conf + frps/frpc-Testconfig (nicht im Repo).
- **Akzeptanz:** beides lokal demonstrierbar grün; Erkenntnisse (Header-Name, Ketten-Format)
  in ADR 0001 §7 nachgetragen.
- **Aufwand:** M · **Risiko:** niedrig · **Abh.:** —
- **Ergebnis:** Beide Spikes grün (Details ADR 0001 §7 „Spike-Ergebnisse"). nginx-Setup für
  A2 bestätigt (`ssl_verify_client on`/`ssl_verify_depth 2`/`$ssl_client_s_dn`-Header +
  `proxy_set_header`-Hygiene); Intermediate-Kette für A7 trägt; ECDSA-Größe (D10) bestätigt.
  Nuance für A2/A8: nginx liefert ohne Cert HTTP 400 statt Handshake-Drop — Upstream bleibt
  unerreichbar, ggf. `444` (Drop) erwägen.

### A1 — PKI-Kernbibliothek + `ca-issuer`-Container (Issuance ohne Enforcement) ✅ ABGESCHLOSSEN 2026-06-11
- **Beschreibung:** Neuer Dienst `apps/ca-issuer/` (Python/FastAPI). Zertifikats-Primitive aus
  `apps/server/app/modules/frp/pki.py` in ein gemeinsames Modul extrahieren und hierher
  verlagern (**Server signiert künftig nicht mehr**, D6). Root (ECDSA P-256, at-rest
  passphrase-verschlüsselt, Passphrase aus Secret/env), gescopte Intermediates
  `tunnel`/`access`/`internal` beim Erststart erzeugen. Endpunkte: `POST /enroll`
  (Einmal-Token → CSR signieren → Leaf+Kette), `POST /renew` (verifizierte Identität →
  neues Leaf). Nur interner Listener. DB-Lesezugriff auf Token-/Deprovision-Liste.
- **Betroffen:** `apps/ca-issuer/**` (neu), `apps/server/app/modules/frp/pki.py` (Signier-Logik
  raus), `docker-compose.yml` (neuer Container + Volume), DB-Modell für Enrollment-Token.
- **Akzeptanz:** Unit-Tests: Root/Intermediate/Leaf-Kette validiert, ECDSA, Laufzeiten pro
  Zielgruppe (native kurz, Browser lang); `/enroll` stellt für gültigen Token aus, lehnt
  ungültig/abgelaufen/verbraucht ab; `/renew` für gültige Identität, verweigert bei
  Deprovision. Container baut, startet, erzeugt Root+Intermediates ins Volume.
- **Aufwand:** L · **Risiko:** mittel (neuer Dienst, Key-Handling) · **Abh.:** A0
- **Fortschritt:** Inkrement 1 (PKI-Engine) ✅, Inkrement 2 (Issuer-Dienst `/enroll`+`/renew`,
  26 Tests) ✅, Inkrement 3 (Dockerfile/Entrypoint/gehashte Lock, First-Boot lokal verifiziert:
  PKI erzeugt, root.key.enc verschlüsselt, Inter-Keys 0600, /healthz ok) ✅. **Offen:**
  Inkrement 4 (`enrollment_tokens` + `revoked_identities` im Server, Migration `9aa48c0eaecb`,
  Migrations-Smoke grün; DB-gestützter `TokenStore` im ca-issuer mit atomarem One-Time-Consume
  via `UPDATE … RETURNING`, sqlite-getestet) ✅. **A1 komplett** (23 ca-issuer- + 163 Server-Tests
  grün). **Bewusst zurückgestellt** (gehört zu A2, wenn der Gateway/Server den Dienst konsumiert):
  Compose-Wiring + CI/ghcr-Publish des ca-issuer + der server-seitige Admin-Endpunkt zum Minten
  von Enrollment-Tokens (Tabelle + Issuer-Konsum stehen, das Mint-UI ist die Konsumentenseite).

### A2 — nginx-Gateway + interne-only Listener (permissive) ✅ ABGESCHLOSSEN 2026-06-11
- **Beschreibung:** `gateway`-Container (nginx) vor `:443`. `server` + `ca-issuer` auf
  **internes Netz, plain-HTTP, kein Host-Port** umstellen. Gateway terminiert TLS (access-Leaf,
  vom Issuer ausgestellt), pro Listener: Datenebene **`CERT_OPTIONAL` (permissive!)**,
  Enroll-Listener certless+Token. **Header-Hygiene** (eingehende `X-Client-*` streifen, aus
  verif. Cert setzen). Web-Cert-Erzeugung wandert vom `docker-entrypoint.sh` ins Gateway-Setup.
- **Betroffen:** `apps/gateway/**` (neu, nginx.conf), `docker-compose.yml`, `apps/server/docker-entrypoint.sh`
  (TLS-Terminierung raus), `apps/server`-Listener (plain-HTTP intern).
- **Akzeptanz:** mit Client-Cert → Header kommt an; ohne → (permissive) erreicht App mit leerer
  Identität; gespoofter `X-Client-*` wird gestreift; `server`/`ca-issuer` vom Host nicht direkt
  erreichbar (Port-Check).
- **Aufwand:** L · **Risiko:** mittel (Topologie-Wechsel) · **Abh.:** A1
- **Fortschritt:** Inkrement 1 (Gateway-Config + Dockerfile, `apps/gateway/`) ✅ — additiv.
  Lokal mit der echten `nginx.conf` verifiziert: `nginx -t` ok; Datenebene routet zu `app` und
  setzt `X-Client-Verify`/`-Cert-CN` aus dem verifizierten Cert (permissive: ohne Cert
  `Verify=NONE`, erreicht App trotzdem); `/ca/renew`→issuer; Enroll-Plane `:8444`
  certless→issuer/enroll, gespoofte `X-Client-*`-Header gestrippt; Fremdpfad→404.
- **Inkrement 2 (der brechende Teil) ✅ ABGESCHLOSSEN 2026-06-11:** Produktiv-Compose umverdrahtet.
  - **Cert-Entscheidung: access-Leaf vom ca-issuer** (nicht Bootstrap-self-signed). Begründung:
    native Clients (Desktop/Agent, A4/A5) pinnen die Root und validieren jedes Leaf dagegen (D2)
    — ein self-signed Gateway-Leaf würde abgelehnt. Henne-Ei gelöst: der ca-issuer mintet beim
    First-Boot das access-signierte Gateway-Leaf selbst (`pki.build_server_leaf` →
    `storage.ensure_gateway_cert`, env-gated `CA_GATEWAY_CERT_DIR`) und legt
    `gateway-fullchain.pem`/`gateway.key`/`client-ca.pem` ins gemeinsame `gateway-certs`-Volume;
    das Gateway-Entrypoint wartet darauf, dann `nginx`. **D6 gewahrt** — das Gateway hält nur ein
    Leaf, keinen Signier-Key (Inkrement 2a, 6 neue Tests).
  - **Topologie (Inkrement 2b):** `server` lauscht plain-HTTP `:8080` (TLS-Terminierung +
    Self-Signed-Block aus `docker-entrypoint.sh` raus, openssl/`/app/certs` als Orphans entfernt);
    `server` + `ca-issuer` ohne Host-Port (nur Compose-Netz); `gateway` auf `:443` + Enroll `:8444`;
    neue Volumes `ca-pki` (issuer-privat) + `gateway-certs`; ca-issuer in Compose + ghcr-Publish
    (`docker.yml`-Matrix); `CA_ROOT_PASSPHRASE` in `.env.example` + `init-secrets.sh`.
  - **Bug gefunden & gefixt (Stack-Up):** frisches `gateway-certs`-Named-Volume ist root-owned —
    der ca-issuer-Entrypoint chownt es jetzt vor dem gosu-Drop.
  - **Verifiziert (`docker compose up`, lokal):** Web/API über `:443` permissiv ohne Client-Cert
    → 200; Gateway-Leaf `CN=localhost`/issuer `Access Intermediate` (kettet zur Root, nicht
    self-signed); `ca-issuer` + `server` vom Host nicht erreichbar (8090/8080/8443 refused);
    `/healthz` grün; gespoofter `X-Client-Verify: SUCCESS` vom Gateway überschrieben → issuer 401;
    Enroll `:8444` route (Fremdpfad 404, bogus Token 403). Docs DE+EN nachgezogen (Installation/
    Betrieb/Troubleshooting/Developer); das **vollständige** PKI/mTLS-Modell bleibt A10.
  - **Datenebene weiterhin permissiv** (`ssl_verify_client optional`); Scharfschalten ist A8.

### A3 — Server: Cert-Scope + Per-Route-Authz auf dem Header (permissive) ✅ ABGESCHLOSSEN 2026-06-11
- **Beschreibung:** App liest die Gateway-Identität; Dependency, die CN/Scope → Identität
  mappt; Per-Route-Guards (Agent-Routen ⇒ Agent-Scope, Admin-Routen ⇒ access-Scope).
  Zunächst **log-only/permissive** (warnt, erlaubt), bis Clients Certs haben.
- **Betroffen:** `apps/server/app/core/auth.py` (Scope-Dependency), Router unter
  `app/modules/*/` (Guards), `apps/server/tests/`.
- **Akzeptanz:** Tests: Agent-Scope auf Agent-Route ok / (enforced) auf Admin-Route abgelehnt
  und umgekehrt; permissive loggt, erlaubt.
- **Aufwand:** M · **Risiko:** niedrig-mittel · **Abh.:** A2
- **Fortschritt ✅ ABGESCHLOSSEN 2026-06-11:** Scope-Schicht in **neuem** `app/core/identity.py`
  (statt `auth.py` — die mTLS-Identität ist orthogonal zu JWT/API-Key, zweiter Faktor D3):
  `ClientIdentity` + `get_client_identity` (parst den vom Gateway weitergereichten Cert-PEM
  authoritativ, wie der ca-issuer auf `/renew`) + `require_scope(*allowed)` (Factory).
  - **Scope-Entscheidung:** `access` = Mensch (Desktop/Browser/Extension), **`tunnel` = Agent**
    (ADR §3.1: Agent-/Visitor-Certs unter der tunnel-Intermediate; D8 trennt Mensch/Agent auf
    `:443` per Scope). Zentral als Konstanten `SCOPE_ACCESS`/`SCOPE_AGENT` — A4 kann es bei der
    Enrollment-Umsetzung bestätigen/anpassen.
  - **Permissiv-Schalter:** `MTLS_ENFORCE` (Default `false`, `core/config.py`). Permissiv: ein
    Mismatch wird geloggt (WARNING nur bei *falschem* Cert-Scope, DEBUG beim erwarteten
    „noch-kein-Cert"), Request **läuft durch**. A8 setzt `MTLS_ENFORCE=true` → 403.
  - **Guards angewandt:** Router-Level `access` für pure Human/Admin-Router (users, api_keys,
    connections, ansible, servers + frp config/tunnel/generate/status/pki); per-Route `tunnel`
    für Agent-Push (`/api/monitoring/agent/{id}/report`); **`tunnel`+`access`** für den dual-use
    frpc-Sync (`frp/provision_router`, Agent *oder* Admin lesen dieselbe Config); `access` für
    Monitoring-Proxy-Admin + Provision-Token-Mint/List.
  - **Bewusst offen gelassen** (Enforcement-Nuance = A8): `auth_router` (Login/Bootstrap),
    `hooks/trigger/{token}` (öffentlicher Webhook-Ingest, externe Aufrufer ohne Cert),
    `provision/activate` (Bootstrap-Tür, certless wie enroll), SPA/Static.
  - **Tests:** `tests/test_mtls_scope.py` (18) — Identity-Parsing + `require_scope` permissiv/
    enforced (inkl. dual-use) als Unit; Integration via TestClient: permissiv durchlässig (401
    von Auth statt 403), enforced 403 ohne Cert, 200 mit access-Cert+JWT, 403 mit tunnel-Cert
    auf Admin-Route, dual-use akzeptiert tunnel, Bootstrap nie 403. **181 Server-Tests grün**
    (keine Regression — permissiv = durchlässig). Developer-Doku zum Scope-Modell bleibt A10.

### A4 — Agent: Auto-Enrollment + mTLS (Go)
- **Beschreibung:** Beim Provisioning (bestehender Einmal-Token-Flow) ECDSA-Keypair + CSR
  on-device, `ca-issuer/enroll` über Gateway, Cert+Key als 0600-Datei, CA pinnen. Client-Cert
  für alle Server-Pushes (gemeinsamer `internal/httpclient` bekommt `Identity` + custom-root-only).
  Auto-Renew bei ~50 % Laufzeit via `/renew`.
- **Betroffen:** `apps/agent/internal/provision/`, `internal/httpclient/`, `internal/monitor/report.go`,
  neue `*_test.go`.
- **Akzeptanz:** Go-Tests (Keygen/CSR/Renew-Entscheidung); lokale Integration: Agent enrollt,
  pusht mit Client-Cert, erneuert. Cross-Builds linux+windows grün.
- **Aufwand:** L · **Risiko:** mittel · **Abh.:** A1, A2, A3

### A5 — Desktop: Auto-Enrollment + mTLS + Browser-P12-Export (Rust/Tauri)
- **Beschreibung:** Beim ersten Server-Login ECDSA-Keypair+CSR (`rcgen`), Enroll via
  `ca-issuer`, Cert+Key in den Keyring (ECDSA passt; **Datei-Fallback** bei Windows-Limit),
  CA pinnen (`tofu.rs`: CA statt Leaf), `reqwest` `identity()` + `tls_certs_only()`. Auto-Renew.
  **Browser-P12-Export** (Cert erzeugen/signieren, als PKCS12 exportieren).
- **Betroffen:** `apps/desktop/src-tauri/src/{auth.rs,tofu.rs,sync.rs,commands.rs}`,
  neues Enrollment-Modul, Tests.
- **Akzeptanz:** cargo-Tests für reine Logik (CSR-Bau, Renew-Scheduling, P12-Packaging);
  Plattform-Verifikation dokumentiert (Linux; **Windows-Keyring-Größe manuell prüfen**).
- **Aufwand:** XL → **aufteilen** (A5a Enroll, A5b Renew, A5c P12-Export) · **Risiko:**
  mittel-hoch (Keyring-Plattform) · **Abh.:** A1, A2

### A6 — Browser + Extension
- **Beschreibung:** Web-SPA hinter mTLS (kein `fetch`-Code-Change, aber P12-Import dokumentieren);
  token-gegateter Enroll-Pfad (certless Listener), der ein Browser-P12 liefert (Fallback zum
  Desktop-Export). Extension: Host braucht importiertes Cert (V5) — dokumentieren/abfangen.
- **Betroffen:** `apps/web/` (Doku/Onboarding-Hinweis), `apps/extension/` (Doku),
  Enroll-Endpoint (P12-Variante).
- **Akzeptanz:** mit importiertem P12 lädt die SPA + Login funktioniert; ohne → Handshake
  scheitert (erwartet). Extension erreicht API bei vorhandenem Host-Cert.
- **Aufwand:** M · **Risiko:** mittel (Browser-UX) · **Abh.:** A2, A5c

### A7 — frps unter die `tunnel`-Intermediate
- **Beschreibung:** `ca-issuer` signiert frps-Server-Cert + Agent-Tunnel-Client-Certs unter
  `tunnel`; frps-Materials publizieren (Logik aus Server raus, Isolation `frp-pki`⇏frps wahren);
  `trustedCaFile` = Kette (aus A0-Spike bestätigt).
- **Betroffen:** `apps/server/app/modules/frp/` (Publish-Pfad), `ca-issuer`, `docker-compose.yml`
  (frps-Volumes unverändert isoliert).
- **Akzeptanz:** frischer Agent zieht Tunnel-Client-Cert aus der neuen Kette, baut STCP-Tunnel;
  frps verifiziert gegen die Intermediate-Kette.
- **Aufwand:** L · **Risiko:** mittel · **Abh.:** A1, A4

### A8 — Enforcement umlegen (permissive → `CERT_REQUIRED`)  ⚠ Schlüssel-Task
- **Beschreibung:** Gateway-Datenlistener auf `CERT_REQUIRED`, App-Authz von permissive auf
  enforced. **Erst** wenn A3–A7 beweisen, dass alle Clients enrollen+vorweisen können.
  Bootstrap-Ausnahme: Enroll-Listener bleibt certless+Token.
- **Betroffen:** `apps/gateway/nginx.conf`, App-Authz-Schalter.
- **Akzeptanz:** kein Client erreicht die Datenebene ohne gültiges, gescoptes Cert; Enrollment
  funktioniert weiter; **getesteter Rollback** (zurück auf permissive); „kann mich nicht
  aussperren"-Prozedur (Bootstrap-Token) dokumentiert.
- **Aufwand:** M · **Risiko:** **HOCH** (Lock-out-Moment) — gestaffelt + Rollback bereit · **Abh.:** A3,A4,A5,A6,A7

### A9 — Backup/Restore inkl. CA-Kronjuwel (parallel ab A1)
- **Beschreibung:** `scripts/backup.sh` / `restore.sh`: `ca-issuer`-Volume (Root+Intermediates),
  `./certs`, `.env`, `pg_dump` beider DBs, `monitoring-data`; `victoria-data` optional. Root-
  Passphrase **getrennt** (Doku). `pg-backup.sh`-Scope erweitern.
- **Betroffen:** `scripts/`, Doku.
- **Akzeptanz:** Backup → Wipe → Restore reproduziert lauffähigen Stack inkl. CA (Agenten weiter
  vertraut); Passphrase nicht im Tarball.
- **Aufwand:** M · **Risiko:** mittel · **Abh.:** A1

### A10 — Doku DE+EN + CHANGELOG + ADR-Status
- **Beschreibung:** `docs/` (admin + developer, beide Sprachen): PKI/mTLS-Modell, Enrollment,
  P12-Import, Backup; README; CHANGELOG; ADR 0001 → „Implemented".
- **Betroffen:** `docs/**`, `README.md`, `CHANGELOG.md`, ADRs.
- **Akzeptanz:** frischer Clone/Quick-Start stimmt; DE+EN synchron.
- **Aufwand:** M · **Risiko:** niedrig · **Abh.:** alle

---

## Querschnitts-Risiken (im Blick behalten)
1. **A8 Lock-out** — der einzige „scharfe" Moment; permissive-Phase + Rollback sind die Absicherung.
2. **Windows-Keyring (A5)** — ECDSA gewählt (D10), trotzdem manuell auf echtem Windows verifizieren (CI-Blindspot).
3. **frps-Intermediate-Kette (A7)** — durch A0-Spike vorab abgesichert.
4. **Header-Vertrauen (A2)** — interne-only Listener + Header-Stripping sind Pflicht, nicht optional.

## Reihenfolge-Empfehlung
A0 → A1 → A2 → A3 → (A4 ∥ A5 ∥ A7 ∥ A6) → A8 → A10; A9 ab A1 parallel.
Jeder Task ist einzeln test-/commitbar; Implementierung bewusst pro Baustein, nicht „big bang".
