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

### A1 — PKI-Kernbibliothek + `ca-issuer`-Container (Issuance ohne Enforcement)
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
  Inkrement 4 (`enrollment_tokens`-Tabelle im Server + Alembic-Migration + DB-gestützter
  `TokenStore`) **sowie** Compose-Wiring + CI/ghcr-Publish des Dienstes — Letzteres bewusst
  zurückgestellt, bis der Gateway/Server (A2) den Dienst konsumiert, um keine unpublizierte
  Image-Referenz in die Produktiv-Compose zu legen.

### A2 — nginx-Gateway + interne-only Listener (permissive)
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

### A3 — Server: Cert-Scope + Per-Route-Authz auf dem Header (permissive)
- **Beschreibung:** App liest die Gateway-Identität; Dependency, die CN/Scope → Identität
  mappt; Per-Route-Guards (Agent-Routen ⇒ Agent-Scope, Admin-Routen ⇒ access-Scope).
  Zunächst **log-only/permissive** (warnt, erlaubt), bis Clients Certs haben.
- **Betroffen:** `apps/server/app/core/auth.py` (Scope-Dependency), Router unter
  `app/modules/*/` (Guards), `apps/server/tests/`.
- **Akzeptanz:** Tests: Agent-Scope auf Agent-Route ok / (enforced) auf Admin-Route abgelehnt
  und umgekehrt; permissive loggt, erlaubt.
- **Aufwand:** M · **Risiko:** niedrig-mittel · **Abh.:** A2

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
