<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

# ADR 0003 — Entkoppelte Enrollment-Tür (Bootstrap unter erzwungenem mTLS)

- **Status:** **In Umsetzung (Phase B)** — Stand 2026-06-12. Entscheidungen getroffen (§6,
  vorläufig/umlenkbar), Increment 1 (Server-Token-Mint für fremde Identität) ✅ — siehe §9.
- **Betrifft:** `apps/gateway` (Enroll-Plane `:8444`), `apps/server` (Token-Mint + Bootstrap),
  `apps/desktop` (Erst-Enrollment-Flow), Doku.
- **Basis:** [ADR 0001](0001-unified-pki-and-secure-deployment.md) (D3, D8), die A8-„Bekannte
  Grenze" in [ADR 0002](0002-phase-a-task-plan.md).

---

## 1. Problem

Unter `MTLS_ENFORCE=true` setzt das Gateway die Datenebene `:443` auf `ssl_verify_client on`
(`CERT_REQUIRED`). Ein certloser Client wird dann **schon am TLS-Handshake** abgewiesen (verifiziert
in ADR 0001 §7: certlos → `400 No required SSL certificate`). Das trifft **jede** Route auf `:443` —
auch Login/Bootstrap, denn die App-seitigen Per-Route-Ausnahmen aus A3 greifen erst *hinter* dem
Handshake, den ein certloser Client gar nicht erst besteht.

Der heutige Desktop-Erst-Enrollment-Flow ist aber **an den Login gekoppelt**:

```
Login (POST /api/auth/login, :443, JWT)  →  Mint (POST /api/enrollment/token, :443, JWT-gated)  →  Enroll (:8444)
        └────────────────────── beides braucht :443 ──────────────────────┘
```

Ein brandneuer certloser Client kommt also nicht an Schritt 1 vorbei → kein Token → kein Cert.
Henne-Ei. Der aktuelle Workaround (ADR 0002 A8) ist ein **kurzes permissives Fenster** beim
Onboarding — operativ unschön und schwächt die Posture genau im Onboarding-Moment.

Der **Agent** hat dieses Problem nicht: Ein Admin stellt out-of-band einen Einmal-Provision-Token
aus, den der Agent direkt an `:8444` einlöst — **ohne Login**. Enrollment und Authentifizierung sind
beim Agent bereits entkoppelt. Diese Skizze überträgt das Modell auf Menschen/Desktop.

## 2. Ziel

- Die Datenebene `:443` bleibt **dauerhaft hart** (`CERT_REQUIRED`), 24/7, ohne permissive Fenster.
- **Alles** Onboarding läuft über die **certless, token-gegatete** Enrollment-Plane `:8444`.
- Enrollment (Cert holen) wird vom Login (JWT holen) **entkoppelt**: erst Cert per Token, dann
  Login auf `:443` mit Cert.

## 3. Entwurf: zwei klar getrennte Planes

| Plane | TLS | Exponiert | Autorisierung |
|---|---|---|---|
| **`:443` Datenebene** | `CERT_REQUIRED` (hart) | die **ganze** App + Login + Normalbetrieb | Client-Cert (Handshake) **+** JWT/Scope (App) |
| **`:8444` Enroll-/Bootstrap-Plane** | certless (TOFU-pin CA) | **nur** `/enroll` + die Erst-Admin-Bootstrap-Route | **Einmal-Token** bzw. Bootstrap-Token (App), nie ein Cert |

Schlüsselprinzip: Auf `:8444` ist **nicht das Cert** die Zugangskontrolle, sondern der **Einmal-
Token**. Das Cert ist das Ergebnis, nicht die Voraussetzung. Die Plane bleibt streng auf
Enrollment-/Bootstrap-Routen allowlisted — **keine** Daten-Routen, Identitäts-Header werden
gestrippt (wie heute), Rate-Limit aktiv.

### 3.1 Die drei Onboarding-Flüsse

**A — Erster Admin** (kein Admin existiert, kein Cert):
```
Server schreibt beim First-Boot data/.bootstrap_token
  → POST /auth/bootstrap {token, user, pw}   auf :8444 (certless)   → Admin angelegt
  → derselbe Aufruf liefert einen Enroll-Token mit
  → Enroll (:8444, Token → Cert)                                    → Admin hat Cert
  → ab jetzt :443 mit Cert (Login, Normalbetrieb)
```

**B — Neuer Mensch** (ein Admin existiert bereits):
```
Admin (auf :443, mit Cert) mintet einen Einmal-Enroll-Token für die neue Identität
  → reicht ihn out-of-band weiter (Copy-Paste/QR, wie Agent-Provision heute)
  → Desktop des Neuen: „Mit Token enrollen" → Enroll (:8444, Token → Cert)
  → dann Login auf :443 (Cert + Username/Passwort)
```

**C — Neuer Agent**: **unverändert** — Admin stellt Provision-Token aus, Agent enrollt an `:8444`.
Das Modell aus B ist exakt die Verallgemeinerung von C auf den `access`-Scope.

## 4. Was sich ändert (Komponenten-Skizze)

- **Gateway `:8444`** — nginx-Allowlist erweitern: zusätzlich zur `/enroll`-Route die minimale
  Bootstrap-/Token-Route(n) zum `server`-Upstream proxen (weiterhin Identitäts-Header strippen,
  Rate-Limit, alles andere → 404). Strikte Allowlist, **kein** Daten-Pfad.
- **Server** —
  1. Admin-Variante des Enroll-Token-Mints: einen Token **für eine fremde Identität** ausstellen
     (nicht nur für den eingeloggten User), inkl. Authz „wer darf wen enrollen".
  2. Die Erst-Admin-Bootstrap-Antwort um einen Enroll-Token ergänzen (Flow A), damit der erste
     Admin in einem Rutsch Cert bekommt.
- **Desktop** — ein **„Mit Token enrollen"**-Erst-Start-Pfad (separat vom Login): Server-URL +
  Token → Enroll an `:8444` → Cert ablegen → danach normaler Login auf `:443`. Spiegelt den
  `provision`-Subcommand des Agents.
- **Doku** — Onboarding-Prozeduren unter Enforcement (ersetzt das permissive Fenster aus A8).

## 5. Sicherheits-Eigenschaften

- **Minimale certless Oberfläche:** `:8444` exponiert ausschließlich Enrollment + Erst-Admin-
  Bootstrap — beide token-gegated, rate-limited, header-gestrippt. Kein Passwort-Login und keine
  Daten-Route certless erreichbar.
- **Token statt Cert als Onboarding-Gate:** konsistent mit dem bestehenden Agent-Provision-Modell;
  der Einmal-/Bootstrap-Token ist kurzlebig, single-use, server-seitig invalidierbar.
- **`:443` ohne Ausnahme:** das Handshake-Tor (D3) bleibt lückenlos — Enforcement muss nie mehr
  temporär gelockert werden.
- **Optionale Härtung:** Da Onboarding selten ist, kann `:8444` netzseitig enger gebunden werden
  (z. B. nur aus Admin-Netzen erreichbar) — unabhängig von dieser Skizze.

## 6. Entscheidungen (Stand 2026-06-12 — vorläufig, umlenkbar)

1. **`:8444` bleibt minimal — nur `/enroll`.** Der allererste Admin wird über das **einmalige
   permissive Setup-Fenster** gelöst, **nicht** über eine certlose `/auth/bootstrap`-Route.
   Begründung: kleinste certlose Angriffsfläche; der Erst-Admin-Bootstrap ist ein seltenes
   Einmal-Ereignis, für das ein kurzes permissives Fenster vertretbar ist.
2. **Authz: jeder Admin darf für beliebige (existierende) Identitäten minten** — analog zum
   Agent-Provision (jeder Admin, pro Identität ein Einmal-Token). Ziel-User muss existieren.
3. **Token-Zustellung: Copy-Paste (out-of-band)** in v1; QR/E-Mail wären Komfort, nicht Pflicht.
4. **Desktop-UX: eigener „Mit Token enrollen"-Erst-Start-Schritt**, analog zum Agent-`provision`-
   Subcommand (getrennt vom Login).

> Diese Entscheidungen sind bewusst **vorläufig** — sie folgen dem Prinzip „certlose Tür klein
> halten". Increment 1 (§9) hängt an **keiner** davon und bleibt auch bei einer Kursänderung gültig.

## 7. Bewusst NICHT (YAGNI)

- **Kein** Standard-Enrollment-Protokoll (SCEP/EST/ACME-Client-Cert) — der vorhandene
  Token→CSR→Issuer-Pfad trägt; ein Industriestandard wäre Over-Engineering für eine
  Single-Operator-Installation.
- **Kein** externer IdP / SSO in v1.
- **Keine** automatisierte Token-Verteilung (QR/E-Mail) in v1.

## 8. Aufwand (grob)

Gateway-Allowlist **S**, Server-Token-Mint-für-Subject + Bootstrap-Erweiterung **M** (inkl. Authz +
Tests), Desktop-„Mit-Token-enrollen"-Flow **M** (Rust + UI + Tests), Doku **S**. Gesamt: ein
abgrenzbarer Phase-B-Block, test-/commitbar pro Komponente — **kein** „big bang".

## 9. Umsetzungsstand

- **Increment 1 — Server: Admin mintet für fremde Identität ✅ 2026-06-12.**
  `POST /api/enrollment/token/for` (admin-only, `get_current_admin`): mintet ein einmaliges
  `access`-Token für einen **existierenden** Ziel-User (CN = dessen Username, issuer-diktiert),
  unbekannter User → `404`, Nicht-Admin → `403`. Mint-Logik mit dem Self-Service-Endpoint in einem
  `_mint_token`-Helper geteilt. 4 neue Tests (`test_enrollment_mint.py`), Server-Suite **190 grün**,
  ruff sauber. API-Referenz DE+EN ergänzt. Hängt an keiner der §6-Entscheidungen.
- **Increment 2 — Gateway:** kein Code nötig — `:8444` bleibt per Entscheidung #1 minimal (nur
  `/enroll`); das war bereits der Stand und ist in `nginx.conf` so dokumentiert.
- **Increment 3 — Desktop: „Mit Token enrollen"-Flow ✅ 2026-06-12.** `enrollment::enroll_with_token`
  (Rust) überspringt `mint_token` (kein JWT) und löst das vorgegebene Token direkt an der
  Default-Enroll-Plane `:8444` ein — CSR-CN nur Platzhalter (Issuer diktiert die CN aus dem Token),
  TLS-Trust per TOFU wie beim Agent. Tauri-Command `enroll_with_token` + Bridge-Wrapper. Das
  `Login.svelte` bekommt einen Modus-Umschalter „Erstes Mal? Gerät mit Token einrichten" (Server-URL
  + Token → enrollen → danach normaler Login). i18n DE+EN. Checks grün: cargo fmt/clippy/test **58**,
  svelte-check 0, eslint/prettier, vitest **73** (inkl. i18n-Parität). Manuelle Real-Enroll-/
  Windows-Keyring-Verifikation bleibt offen (CI-Blindspot, wie A5).
- **Offen:** Increment 4 (Onboarding-Doku unter Enforcement: der vollständige Ablauf „Admin mintet →
  out-of-band → neuer Nutzer enrollt im Desktop → Login", ersetzt das permissive Fenster für
  **Folge**-Clients; das Fenster bleibt nur für den allerersten Admin).
