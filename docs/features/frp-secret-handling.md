<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# FRP: Tunnel-Secrets beim Bearbeiten erhalten, in JSON-Antworten maskieren

Roadmap: R-0113, R-0106, R-0053 · Stand: main@8224e84c · Geplant 2026-09-30 von der Aufsicht, Entscheidungen Kevin 2026-09-30

## Problem / Motivation

Ein STCP-Tunnel braucht ein Secret; Server (frpc) und Visitor tragen es in ihrer TOML-Konfiguration. Beim Anlegen
erzeugt der Server ein Secret, wenn keins kommt. Beim Bearbeiten gilt das nicht:

- `PUT /api/frp/tunnels/{id}` übernimmt ein gesendetes `secret_key: null` oder `""` wörtlich
  (`frp/tunnel_router.py:156`, Schleife `:180–193`); `_check_secret` (`frp/schemas.py:28–36`) lässt beides durch.
  Der Generator schreibt danach `secretKey = "None"` bzw. `secretKey = ""` in frpc- und Visitor-TOML
  (`frp/config_generator.py:171`, `:235`). Ein Wechsel von https auf stcp per PUT ohne Secret endet genauso.
- Der Desktop-Editor schickt beim Bearbeiten immer die volle Nutzlast (`apps/desktop/ui/src/lib/models/frpTunnel.ts`,
  `formToInput`); ein leeres Secret-Feld wird zu `null`. Der Hinweis im Editor lautet auch beim Bearbeiten
  „leer = automatisch generiert“ (`i18n/dictionaries.ts:107`, EN `:702`).
- Das Secret steht in JSON-Antworten, die kein Client liest: Tunnels GET/POST/PUT (`tunnel_router.py:38/133/141/224`),
  `GET /api/frp/status` (`status_router.py:105`), `GET /api/frp/server-config/{id}` (dort trotz `mask_secrets=True`,
  weil `frp/models.py:64` die Tunnel ohne Maske serialisiert) und `/api/servers` (`servers/models.py:53`, Feld
  `frpTunnels`). Gebraucht wird es nur in den erzeugten TOML-Dateien und im Provisioning (Desktop-Visitor über
  `/generate/visitor-bundle`, Agent über `/provision/{id}/config`).
- `_reject_toml_breakers` (`frp/schemas.py:20–25`) lässt U+007F (DEL) durch; TOML verbietet DEL im Basic String, die
  erzeugte `frps.toml` ist dann unlesbar. Ein strikter xfail hält das fest (`tests/test_frp_toml_roundtrip.py:276`).

## Ziel & Nicht-Ziele

Ziel:
- Beim Bearbeiten heißt ein leeres Secret (`null` oder `""`) „unverändert“. Wird ein Tunnel stcp und hat kein Secret,
  erzeugt der Server eins (`FrpTunnel.generate_secret()`, 256 Bit), wie beim Anlegen.
- Der Generator schreibt nie ein leeres Secret: ein stcp-Tunnel ohne Secret wird übersprungen und protokolliert
  (`logger.warning`); die übrigen Tunnel des Hosts bleiben unberührt.
- Bestehende stcp-Tunnel ohne Secret bekommen per Datenmigration je ein eigenes Secret.
- JSON-Antworten liefern `secretKey: null`; das Feld bleibt, damit sich kein Response-Schema ändert. TOML- und
  Provisioning-Routen liefern das Secret unverändert.
- Der Desktop-Editor zeigt beim Bearbeiten „leer = unverändert“ / „empty = unchanged“.
- `_reject_toml_breakers` lehnt U+007F ab.

Nicht-Ziele: ein Knopf „Secret neu erzeugen“ (Rotieren bleibt Eintippen, mindestens 16 Zeichen); ein CHECK-Constraint
in der Datenbank; ein 422 für leere Secrets; Änderungen an Create (leer = erzeugen bleibt); das Weglassen des Felds.

## Betroffene Komponenten & Dateien

- Server: `apps/server/app/modules/frp/tunnel_router.py`, `frp/schemas.py`, `frp/models.py`, `frp/config_generator.py`,
  `frp/status_router.py`, `servers/models.py`, neue Alembic-Migration unter `apps/server/alembic/versions/`.
- Tests: `apps/server/tests/test_frp_tunnels.py`, `test_config_generator.py`, `test_frp_status.py`, `test_frp_config.py`,
  `test_frp_input_hardening.py`, `test_frp_toml_roundtrip.py`, `test_migrations_smoke.py`, ggf. ein Server-Test für
  `/api/servers`.
- Desktop-UI: `apps/desktop/ui/src/lib/i18n/dictionaries.ts`, `src/components/infra/TunnelModal.svelte` (+ Test).
- Doku: `docs/developer/api-reference.html` + EN, `docs/admin/frp-tunnel.html` + EN, `CHANGELOG.md`.

## Datenmodell / API / Migrationen

- Keine Schema-Änderung; `secret_key` bleibt nullable. Datenmigration auf den Head `e5f7a1b3c9d0`: je stcp-Zeile mit
  `secret_key IS NULL OR secret_key = ''` ein eigenes `secrets.token_urlsafe(32)` in Python (kein SQL-`random()`);
  Downgrade ist ein No-op. Vorbild für den Migrationstest: `tests/test_migrations_smoke.py:142`.
- API: Request-Schema unverändert (leer bleibt gültig, bedeutet beim PUT nun „unverändert“). Response-Schema
  unverändert; nur der Wert von `secretKey` wird `null`. `scripts/dev/openapi-breaking.sh` bleibt grün (Zusatzbeleg).
- Folgen der Migration: der Agent holt die neue Konfiguration über den Hash (höchstens 5 Minuten); ein laufender
  Desktop-Visitor dieses Tunnels braucht einen Tunnel-Neustart.

## Externe Integrationen

FRP: STCP-Proxy und -Visitor müssen dasselbe `secretKey` tragen. Ob frp ein leeres `secretKey` ablehnt, ist nicht
verifiziert; nach T2 schreibt der Generator keins mehr. Für gültige Tunnel bleibt die Generator-Ausgabe byte-gleich,
der Provision-Hash ändert sich nicht.

## Trade-offs & Alternativen

- 422 statt „unverändert“: bricht den Desktop-Editor bei jedem Typwechsel und nach dem Maskieren bei jedem Speichern.
- Generator wirft statt zu überspringen: kippt den Agent-Sync, den Hash-Endpunkt und das Visitor-Bundle für alle Tunnel
  des Hosts.
- Nur `/status` maskieren: das Secret bliebe in vier weiteren Antworten, die kein Client braucht.
- Keine Migration: betroffene Tunnel blieben mit dem neuen Generator offline, bis jemand sie bearbeitet.

## Risiken & Rollback

- Maskieren ohne T1 würde bei jedem Bearbeiten das Secret leeren; deshalb hängt T4 an T1.
- Bestehende Tests vergleichen Antworten gegen `to_dict()` und würden eine Maske stumm mitziehen
  (`test_frp_status.py:59`, `test_frp_config.py:297`); T4 prüft `secretKey is None` ausdrücklich.
- `test_frp_tunnels.py:82` prüft das Secret in der POST-Antwort; nach dem Maskieren wird der Test ersetzt
  (`Test-Löschung:`), der Ersatz prüft das erzeugte Secret über die Datenbank.
- Rollback: Revert der Commits; die Datenmigration ist nicht umkehrbar, aber harmlos (sie füllt nur leere Secrets).

## Doku-Impact

API-Referenz DE+EN (Antworten ohne Secret, leer beim PUT = unverändert), Admin-Doku FRP DE+EN (Editor-Verhalten),
CHANGELOG (Fixed/Changed).

## Offene Fragen

Keine; entschieden am 2026-09-30 (unverändert statt 422, alle JSON-Routen maskieren, Datenmigration ohne Constraint,
Generator überspringt, nur Hinweistext im Desktop, schwere Suite Szenario `--tunnel`).
