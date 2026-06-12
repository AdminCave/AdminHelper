<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

# ADR 0001 — Einheitliche interne PKI + sichere Installation/Updates

- **Status:** **Implementiert (Phase-A-Kern, permissiv)** — Stand 2026-06-12.
  Ausstehend: Enforcement-Scharfschaltung (A8).
- **Datum:** 2026-06-11 (Entwurf), 2026-06-12 (Phase-A-Kern umgesetzt)
- **Betrifft:** Server, ca-issuer (neu), Desktop-Client, Go-Agent, Web-Frontend, frps, Install/Update/Backup-Skripte
- **Umsetzung:** siehe [ADR 0002](0002-phase-a-task-plan.md) (Task-Plan A0–A10 mit Fortschritt)
  und den Abschnitt „Umsetzungsstand (Phase A)" unten.

---

## 0. Umsetzungsstand (Phase A) — Stand 2026-06-12

Der **Kern** dieses Entwurfs ist umgesetzt und läuft **permissiv** (nutzbar, ohne dass schon ein
Client ausgesperrt wird). Die Datenebene wird **noch nicht** auf `CERT_REQUIRED` scharfgeschaltet —
das ist der bewusst isolierte Schlüssel-Task A8.

| Entscheidung | Stand |
|---|---|
| D1 Root → tunnel/access/internal | ✅ `ca-issuer` erzeugt die Hierarchie beim First-Boot |
| D2 CA-Pinning + Leaf-Rotation | ✅ Desktop pinnt die CA-Kette (hostname-agnostisch); Agent pinnt die Root |
| D3 mTLS-Pflicht `:443` | ⏳ **permissiv** (`ssl_verify_client optional`); Scharfschalten = A8 |
| D4 kurzlebige Certs, Revocation = Ablauf | ✅ native 90 d / Auto-Renew; `revoked_identities` als Schnell-Widerruf |
| D5 Cert-Laufzeit pro Zielgruppe | ✅ native kurz+auto; Browser lang (`browser=true`) + P12-Re-Import |
| D6 eigener `ca-issuer`, Server nie im Signier-Pfad | ✅ einzige Signier-Capability; Gateway hält nur ein Leaf |
| D7 Root kalt + passphrase-verschlüsselt | ✅ `root.key.enc`; `CA_ROOT_PASSPHRASE` getrennt vom Backup |
| D8 Human+Agent teilen `:443` per Scope | ✅ `access` (Mensch) / `tunnel` (Agent), Per-Route-Guards (permissiv) |
| D9 keine Migration | ✅ frische Hierarchie ab Tag 1 |
| D10 ECDSA-P-256-Leaves | ✅ Agent (Go) + Desktop (rcgen) |
| D11 ein nginx-Gateway vor den HTTP-Planes; frps ausgenommen | ✅ Gateway `:443`/`:8444`; frps eigene TLS-Kante (unter `tunnel`) |

**Client-Enrollment-Stand:** Go-Agent ✅ (A4), Desktop ✅ (A5: Enroll+mTLS+Renew+P12), frps/Tunnel ✅
(A7). **Browser** kann über den Desktop-P12-Export ein Cert bekommen (A5c) — der einzige verbleibende
menschliche Client neben dem Desktop. **Backup/Restore** inkl. CA-Kronjuwel ist umgesetzt +
DR-getestet (A9).

Die mit `[zu verifizieren]` markierten Punkte des Entwurfs sind alle geklärt (§7 „Verifikation").

---

## 1. Kontext & Ziel

AdminHelper soll **einfach installierbar/aktualisierbar** *und* **sehr sicher** sein.
Heute existieren zwei unabhängige Vertrauenssysteme:

1. **Web-TLS** (`./certs`, self-signed, im `docker-entrypoint.sh` erzeugt) — Vertrauen
   per **TOFU-Pinning** (Desktop pinnt das Leaf, Agent pinnt die Server-Identität).
2. **FRP-mTLS-PKI** (`apps/server/app/modules/frp/pki.py`) — eine echte interne CA
   (CA-Key + Server-Cert + per-Agent/Visitor-Client-Certs), Master im server-only
   Volume `frp-pki`, publizierte Teilmenge im `frp-config`-Volume (GHSA-rv39-Split:
   CA-Key kommt nie in den internet-zugewandten frps).

Daneben (kein PKI, aber Identität): `SECRET_KEY` (JWT), `MONITOR_API_KEY`
(Shared Secret Server↔Monitoring), API-/Agent-Keys (Bearer).

**Entscheidung:** Diese fragmentierte Landschaft wird durch **eine** einheitliche,
gehärtete interne PKI ersetzt, die Maschinen- *und* (verpflichtend) menschliche
Client-Identität trägt — als Fundament für mTLS-Pflicht über alle Zugänge.

---

## 2. Getroffene Entscheidungen (verbindlich)

| # | Entscheidung | Begründung |
|---|---|---|
| D1 | **Eigene interne PKI**: Root → gescopte Intermediates (`tunnel`, `access`, `internal`) | Blast-Radius eindämmen: Kompromittierung eines Intermediate rotiert nur dessen Scope, Root bleibt unberührt |
| D2 | **CA + TOFU kombiniert**: Clients **pinnen die CA** und validieren alle Leaves dagegen | Vereint Pinning-Härte (nur *diese* CA, selbst eine unterwanderte Public-CA prallt ab) mit freier Leaf-Rotation |
| D3 | **mTLS-Pflicht auf der Datenebene `:443` — für ALLE, inkl. Browser** | Handshake-Tor: Scanner/Brute-Force/Probing prallen ab, bevor App-Code läuft; Geräte-Cert als zweiter Faktor neben Passwort/JWT |
| D4 | **Kurzlebige Certs** (native: 30–90 d, Auto-Renew) — **Revocation = Ablauf**, kein CRL | Einfachste robuste Sperre; frp-CRL-Support ohnehin unklar |
| D5 | **Cert-Laufzeit pro Zielgruppe**: native kurz+auto; **Browser lang (6–12 Mon.), manueller Re-Import** | Browser kann nicht auto-erneuern (F1); langer Zyklus + serverseitiges Deprovision als eigentlicher Hebel |
| D6 | **Eigener `ca-issuer`-Container** als einzige PKI-Schiene; **Server nie im Signier-Pfad** | Isoliert die Signier-*Capability* aus der exponierten App (F3): Server-Kompromittierung ⇏ Cert-Minting |
| D7 | **Root-Key kalt + passphrase-verschlüsselt**; online-Intermediates im Issuer unbeaufsichtigt nutzbar | Root nur bei Intermediate-Rotation angefasst; Renewals laufen unbeaufsichtigt (F6) |
| D8 | **Human + Agent teilen `:443`**, getrennt durch **Cert-Scope + Per-Route-Authz** (kein separater Agent-Port) | Cert-Scoping erzwingt die Autorisierung bereits; ein dritter öffentlicher Port wäre Over-Engineering (Capability- statt Zielgruppen-Trennung) |
| D9 | **Keine Migration** — frische Hierarchie ab Tag 1 | Es gibt noch keine produktiven Server/Agenten (F4 entfällt) |
| D10 | **ECDSA-P-256-Leaves** (statt RSA-2048) | Passen in das 2560-Byte-Limit des Windows Credential Manager (V4), modern, ideal für kurzlebige Certs |
| D11 | **Ein nginx TLS/mTLS-Gateway** vor den **HTTP-Planes** (`server` + `ca-issuer`); **frps ausgenommen** | uvicorn reicht Client-Certs nicht nativ durch (V1) → Gateway terminiert TLS+mTLS zentral und reicht die verifizierte Identität als Header weiter. frp spricht ein eigenes Protokoll mit eingebackener mTLS → kann nicht generisch geproxt werden, bleibt eigene Kante |

---

## 3. Architektur

### 3.1 Vertrauensmodell (Trust)

```
Root CA  (kalt, passphrase-verschlüsselt, nur zum Intermediate-Rotieren)
   │   ← Clients PINNEN diese CA beim Enrollment (TOFU-Moment über token-gesicherten Kanal)
   ├─ Intermediate "tunnel"    → frps-Server-Cert + Agent/Visitor-mTLS-Certs
   ├─ Intermediate "access"    → Server-Leaf (:443) + Client-Certs (Desktop/Browser)
   └─ Intermediate "internal"  → (Phase B) Dienst-zu-Dienst-mTLS, z.B. Server↔Monitoring
```

- Clients trauen **ausschließlich** der gepinnten Root (eigener Trust-Store, nicht der
  System-Store). Server-Leaves werden gegen die gepinnte Root validiert → Leaf-Rotation
  jederzeit ohne Re-Pinning.

### 3.2 Topologie (Container / Planes)

```
ÖFFENTLICH                                          INTERN (kein Host-Port)
─────────                                           ──────────────────────
gateway (nginx)  :443    TLS/mTLS-Terminierung      server     (plain HTTP)
                         • :443  ssl_verify_client ON  → Datenebene (Mensch+Agent, Cert-Scope)
                         • enroll-Listener: Token, KEIN Cert  → ca-issuer (plain HTTP, signiert)
                         • setzt X-Client-Cert-* aus verif. Cert   monitoring (via Server-Proxy)
                         • streift eingehende X-Client-* ab         victoria / postgres / redis

frps             :7xxx   EIGENE TLS-Kante (frp-Protokoll, mTLS) — NICHT hinter dem Gateway
```

- **`gateway` (nginx, D11)** — einzige öffentliche TLS/mTLS-Instanz für die HTTP-Planes.
  Hält das `access`-Leaf (Terminierung) + CA-*Certs* (public, Client-Verifikation), **keinen
  Signier-Schlüssel**. Pro Listener eigene Client-Auth-Policy (Datenebene `CERT_REQUIRED`,
  Enroll certless+Token). Natürlicher Ort für späteres ACME (Phase C).
- **`server`** — die Anwendung, lauscht **nur intern plain-HTTP**, nie öffentlich. Signiert
  **nie** Zertifikate. Liest die verifizierte Identität aus dem vom Gateway gesetzten Header.
- **`ca-issuer`** — minimal, lauscht **nur intern**; einzige Signier-Capability; `/enroll`
  (Token) + `/renew` (Cert). Liest intern Token-/Deprovision-Liste (DB). Root-Key verschlüsselt
  daneben (kalt).
- **`frps`** — bleibt eigene TLS-Kante (siehe D11-Begründung); direkt auf seinen Ports.

**Gateway-Sicherheitsbedingungen (nicht verhandelbar):** (1) `server`/`ca-issuer` nur im
internen Docker-Netz, kein Host-Port — sonst ist der Identitäts-Header umgehbar; (2) Gateway
**streift eingehende `X-Client-*`-Header ab** und setzt sie ausschließlich aus dem real
verifizierten Cert — sonst Header-Spoofing; (3) Gateway hält keinen Signier-Schlüssel → die
Capability-Isolation (D6) bleibt erhalten, ein kompromittiertes Gateway bedroht die
Header-Integrität der Datenebene, nicht die CA.
- **`ca-issuer`** — eigener, minimaler Container, der **alles rund ums Zertifikat** macht
  und **selbst** autorisiert (Türsteher-Prinzip): kein Client und nicht der Server kann
  ihn zum freien Signieren bringen.
- **`frps`** — bestehende separate Tunnel-Schiene; ihre CA wird Teil der neuen Hierarchie
  (`tunnel`-Intermediate), von Anfang an.

### 3.3 Zertifikats-Lebenszyklus

**Enrollment (erstes Cert)** — über `ca-issuer/enroll`:
- Auth = **Einmal-Token** (kurze TTL, single-use, rate-limited, in DB) — dieselbe Primitive
  wie die heutigen Provisioning-/Bootstrap-Token.
- Native Clients (Desktop/Agent): erzeugen **on-device** ein Schlüsselpaar + CSR, der Issuer
  signiert. **Privater Key verlässt das Gerät nie.** Cert+Key → OS-Keyring (Desktop) bzw.
  0600-Datei (Agent); Root-CA wird lokal gepinnt.
- **Leaf-Schlüssel = ECDSA P-256** (verifiziert, siehe §7/V4): RSA-2048 PEM (Key+Cert)
  sprengt das Windows-Credential-Manager-Limit von 2560 Bytes; ECDSA P-256 (~1 KB) passt,
  ist modern und für kurzlebige Certs ohnehin die bessere Wahl. Fallback auf 0600-Datei im
  App-Data, falls der Keyring doch zu klein ist.
- Browser: kann nicht programmatisch CSR erzeugen → P12 wird bereitgestellt. Bevorzugt
  **vom Desktop-Client erzeugt+exportiert** (Key entsteht auf einem kontrollierten Gerät);
  Fallback: Issuer erzeugt das P12 für token-basiertes Browser-Enroll (Key issuer-seitig
  geboren, über die TOFU-vertraute Enrollment-TLS ausgeliefert). Einmaliger Import.

**Renewal (Folge-Certs)** — über `ca-issuer/renew`:
- Auth = **das aktuelle, noch gültige Cert** (rein kryptografisch vom Issuer prüfbar:
  von unserem Intermediate signiert + nicht abgelaufen). **Ohne Server.**
- Native: automatisch bei ~50 % Laufzeit + Überlappung → ein kurzzeitig nicht erreichbarer
  Issuer sperrt niemanden aus. Browser: manuell zum Ablauf (D5).

### 3.4 Deprovisionierung ohne CRL (wichtige Präzisierung zu D4)

„Revocation = Ablauf" wirkt auf der **TLS-Schicht**. Für *sofortiges* Kappen eines
kompromittierten/ausgemusterten Geräts **vor** Ablauf gibt es zwei App-Ebenen-Hebel:
1. **Renewal-Verweigerung**: Der Issuer prüft beim `/renew` eine serverseitige
   Aktiv-/Deprovision-Liste → das Cert wird nicht erneuert und stirbt zum Ablauf.
2. **Aktiv-Prüfung pro Request** auf `:443` (App-Ebene, billig) → Zugang sofort entzogen,
   ohne auf den TLS-Ablauf zu warten.

Das ist der praktische Schnell-Widerruf ohne CRL-Maschinerie.

---

## 4. Sicherheits-Eigenschaften (warum dieses Design)

- **Handshake-Tor (D3):** `:443` ist `CERT_REQUIRED` — keine Ausnahme, keine Per-Route-
  Lücke. (Eine Per-Route-Ausnahme würde den Listener auf `CERT_OPTIONAL` zwingen und das
  Tor entwerten — deshalb die separate Schiene statt eines „Lochs".)
- **Capability-Isolation (D6):** Der Signier-Schlüssel liegt nur im `ca-issuer`, und nur
  *er* löst Signaturen aus (nach eigener Prüfung). Server-Kompromittierung ⇏ Cert-Minting.
- **Blast-Radius (D1/D7):** Root kalt+verschlüsselt; ein geleaktes Intermediate rotiert
  nur seinen Scope.
- **Pinning + Rotation (D2):** Selbst eine unterwanderte öffentliche CA wird nicht
  akzeptiert; gleichzeitig sind Server-Leaves frei tauschbar.

---

## 5. Betrieb: Backup / Restore / Disaster Recovery

**Backup-Kronjuwel** ist die Identität, nicht die Datenbank:

| State | Mechanismus | Verlust = |
|---|---|---|
| `ca-issuer`-Keys (Root + Intermediates) | tar des Volumes (Root bleibt verschlüsselt) | **gesamtes Vertrauen weg → alles neu enrollen** |
| `./certs` (Web-Leaf, TOFU-gepinnt) | Datei-Kopie | Desktop/Agent-Pins brechen → alle neu pinnen |
| `.env` (Secrets) | Datei-Kopie 0600 | DB nicht entschlüsselbar / Login kaputt |
| `postgres` (beide DBs) | `pg_dump` (logisch, portabel) | Config/User/Inventar weg (rekonstruierbar) |
| `monitoring-data` | tar | kleiner lokaler State |
| `victoria-data` | tar (**optional**, groß) | nur Metrik-Historie |

- **Root-Passphrase getrennt** vom verschlüsselten Root-Key aufbewahren (Passwortmanager,
  nicht im Backup-Tarball) — sonst ist die Verschlüsselung wertlos (F6).
- Backup-FIRST bei jedem Update; Restore = Volumes + `.env` + `./certs` zurück, dann
  `pg_restore`, dann `up -d` (App re-publiziert frps-Materials aus dem Issuer + DB).

---

## 6. Phasen

- **Phase A (Kern):** Root + `access`/`tunnel`-Intermediates; `ca-issuer`-Container mit
  `/enroll`+`/renew`; `:443` auf mTLS-Pflicht; Per-Route-Cert-Scope (Human vs Agent);
  Desktop-/Agent-Auto-Enrollment; Browser-P12-Export; vollständiges Backup inkl. CA.
- **Phase B (Härtung):** Intermediate `internal`; Server↔Monitoring von `MONITOR_API_KEY`
  auf mTLS umstellen.
- **Phase C (optional/später):** öffentliches ACME (Let's Encrypt) als *zusätzlicher*
  Browser-Trust-Pfad, falls je nötig; ggf. separate Agent-Ingest-Schiene **nur** bei
  belegter Last/Assurance-Anforderung.

**Bewusst NICHT (jetzt):** separater Agent-Port (D8), CRL/OCSP (D4), Offline-Root,
HSM/Vault, Migration (D9).

---

## 7. Verifikation (abgeschlossen 2026-06-11, gegen offizielle Quellen)

- **V1 — uvicorn/Starlette mTLS: TLS-Ebene ✅, App-Durchreichung ⚠️.**
  `--ssl-cert-reqs 2` (= `ssl.CERT_REQUIRED`) + `--ssl-ca-certs` erzwingen Client-Certs am
  Handshake — bestätigt. **Aber:** Starlette legt das verifizierte Cert *nicht* nativ in den
  Request-Scope (offener uvicorn-Issue #745, FastAPI #2224/#7176). **Konsequenz:** Per-Route-
  Cert-Authz (D8) braucht entweder fragiles Transport-Extrahieren *oder* — empfohlen — einen
  **Reverse-Proxy** (nginx) zur mTLS-Terminierung + Header-Weitergabe. Siehe §3.2 + offene Frage.
- **V2 — frp-mTLS ✅, CRL bestätigt NICHT vorhanden ✅ (validiert D4).**
  `transport.tls.certFile/keyFile/trustedCaFile` unterstützen bidirektionale Verifikation
  (frps prüft frpc-Certs gegen die CA). CRL wird beim Handshake **nicht** erzwungen (offener
  frp-Issue #4592) → unsere Entscheidung „Revocation = Ablauf, kein CRL" ist nicht nur Wahl,
  sondern bei frp ohnehin die einzige verlässliche Option. Intermediate-Kette: CA-Datei muss
  die Kette enthalten (Mechanismus vorhanden, praktischer Test in Phase A).
- **V3 — reqwest ✅.** Client-Cert via `identity(Identity)` (PEM/PKCS12), ausschließlicher
  Custom-Root via `tls_certs_only()` (deaktiviert System-Roots) — beides offiziell, rustls-Feature.
- **V4 — Windows-Keyring-Limit bestätigt: 2560 Bytes** (`CRED_MAX_CREDENTIAL_BLOB_SIZE = 5*512`).
  → **ECDSA-P-256-Leaves** (passen, ~1 KB) statt RSA-2048; Fallback 0600-Datei. In §3.3 verankert.
- **V5 — Browser-Extension (entfallen, 2026-06-12).** Die frühere Extension rief den Server im
  Browser-Kontext per `fetch(..., {headers:{'X-API-Key'}})` und hätte unter mTLS-Pflicht ein
  Host-Client-Cert im OS/Browser-Store gebraucht (nicht programmatisch wählbar). Sie wurde
  **vollständig aus dem Projekt entfernt** (`apps/extension/` gelöscht, CI-/Release-Jobs raus) —
  die mTLS-Kompatibilitätsfrage entfällt damit ersatzlos. Menschliche Browser-Nutzung läuft über
  das vom Desktop exportierte P12 (A5c).

Quellen: uvicorn.org/settings, github.com/fastapi/fastapi#2224 + Kludex/uvicorn#745,
gofrp.org/en/docs/features/common/network/network-tls + fatedier/frp#4592,
docs.rs/reqwest ClientBuilder, Microsoft Learn wincred.h (CREDENTIALW).

### Spike-Ergebnisse (A0, lokal verifiziert 2026-06-11)

Mit echter ECDSA-Test-PKI (Root → `access`-Intermediate → Server-/Client-Leaf):

- **Spike 1 — nginx mTLS + Header (V1 bestätigt):** `ssl_verify_client on` +
  `ssl_verify_depth 2` + `ssl_client_certificate=root+intermediate`. Gültiges Client-Cert →
  Upstream erhält `X-Client-Cert-CN: CN=test-agent-01` und `X-Client-Verify: SUCCESS`. Ohne
  Cert → **HTTP 400, Upstream nie erreicht** (nginx beantwortet mit 400 statt Handshake-Abbruch
  — Schutz hält, App unerreichbar). Vom Client gespoofter `X-Client-Cert-CN` wird durch
  `proxy_set_header` mit der echten DN **überschrieben** (Header-Hygiene bestätigt).
- **Spike 2 — Intermediate-Kette (V2 bestätigt):** mutual TLS mit Intermediate-signierten
  Leaves beidseitig, `CAfile=root+intermediate`, `-Verify 2` → `Verify return code: 0 (ok)`.
  Die `tunnel`-Intermediate-Kette für frps trägt also (CA-Datei = Kette, depth 2).
- **D10 bestätigt:** ECDSA-P-256 Key+Cert in PEM = **858 Bytes** (< 2560 Windows-Keyring-Limit;
  RSA-2048 wäre ~3 KB gewesen).

---

## 8. Bezug zum Install/Update-Plan

Das Install-Skript erzeugt die CA **nicht** — der `ca-issuer` tut das selbst beim ersten
Start. Aufgaben des Skripts: Container/Volumes anlegen (Isolation `frp-pki` ⇏ frps
bewahren, Compose verbatim aus dem Release), `init-secrets.sh`, `DOMAIN` setzen, ersten
Enrollment-/Bootstrap-Token ausgeben. Bezug über **verify-then-run** (Download + SHA256
+ `sudo bash`), versions-**gepinnt**. Update = Backup-first (inkl. CA) → pinned pull →
Alembic-Migration → Healthcheck → Restore-Hinweis. (Details: separater Install/Update-Plan.)
