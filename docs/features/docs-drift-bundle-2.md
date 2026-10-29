<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Doku-Drift, zweites Bündel: veraltete Doku, Kommentare und zwei Test-Ergänzungen

Stand des Codes: `origin/main@c16ebb9f`. Die `datei:zeile` der Roadmap-Zeilen stammen von älteren Ständen und sind
teils verrutscht; die Zeilen unten sind frisch gegriffen, der Bauer greppt sie vor jeder Task erneut. Ledger:
`tasks/docs-drift-bundle-2.md`. Roadmap: R-0829, R-0841 (= R-0905), R-0848, R-0849, R-0850, R-0853, R-0863 (nur
`agent-deployment.html`), R-0866, R-0874, R-0898, R-0904 (= R-0919).

## Problem / Motivation

Elf Funde aus Branch-Prüfungen von 2026-10-22/23: Doku und Kommentare beschreiben einen Stand vor `mtls-consistency`,
`smtp-hardening`, `compose-hardening`, `ops-install-hardening` und `hooks-hardening`. Falsche Doku ist ein Bug
(`.claude/rules/docs.md`). Beispiele: `docs/admin/installation.html:161` (EN `:113`) sagt „Datenebene läuft permissiv“, obwohl
`MTLS_ENFORCE` seit 0.29.0 `true` ist; `docker-compose.yml:227-229` spricht von „permissive window … before arming“, `:211`
von „permissive mTLS this phase; CERT_REQUIRED in A8“; `docker-compose.yml:46-49` und `apps/server/docker-entrypoint.sh:48-51`
begründen die `X-Client-*`-Header mit einem unerreichbaren Socket, obwohl `identity.py` (`_peer_is_gateway`, `:111`) die
Gegenstelle prüft; `.env.example:146-155` und die Env-Tabelle im README führen SMTP nur für den Hub.

## Ziel & Nicht-Ziele

Ziel: jede Stelle sagt, was der Code tut. Nicht-Ziele: keine Verhaltensänderung, kein neuer Test außer den zwei
Lücken in `frpc.rs` (JoinHandle des 401-Tests, Warten auf den Admin-Port in `stop_left_behind`), keine Änderung an
`.github/workflows/` (R-0847/R-0877 bleiben bei Kevin), keine Paketierung (`postinst`, `adminhelper-agent.spec`,
`packaging_rpm_test.go` aus R-0863 bleiben offen, Install-Pfad). R-0905 und R-0919 sind als Dubletten abgelehnt.

## Betroffene Komponenten & Dateien

- Doku: `docs/admin/installation.html`, `docs/en/admin/installation.html`, `docs/admin/troubleshooting.html`,
  `docs/en/admin/troubleshooting.html`, `docs/admin/benutzer.html`, `docs/en/admin/users.html`, `docs/admin/betrieb.html`,
  `docs/en/admin/operations.html`, `docs/admin/agent-deployment.html`, `docs/en/admin/agent-deployment.html`,
  `docs/developer/index.html`, `docs/en/developer/index.html`, `docs/developer/server.html` (+ en),
  `docs/developer/desktop.html` (+ en), `README.md`, `.env.example`, `CHANGELOG.md`.
- Kommentare: `docker-compose.yml`, `apps/server/docker-entrypoint.sh`, `apps/desktop/ui/src/lib/utils/shell.ts`,
  `apps/desktop/src-tauri/src/{launcher,frpc,terminal}.rs`.
- Text/i18n: `apps/web/src/lib/i18n/dictionaries.ts` (`modal.hook.cronFormat`, DE `:206`, EN `:504`: „(UTC)“).

## Datenmodell / API / Migrationen

Keine. Der Hinweistext in `dictionaries.ts` ist ein UI-String, kein API-Vertrag.

## Externe Integrationen

Nur R-0898: „Compose v2.6+“ (`installation.html:84`) ist laut Zeile unverifiziert; vor dem Schreiben in der offiziellen
Compose-Doku (Referenz `pids_limit`/`sysctls`, Release Notes) nachlesen und Unbelegtes als „nicht verifiziert“ markieren.

## Trade-offs & Alternativen

Ein Bündel statt elf Mini-Vorhaben: gleiche Art (Doku), ein Reviewer-Profil. Getrennt bleiben Doku (scripts), Web,
Desktop-UI und Desktop-Rust, weil jede Komponente ein eigenes `Verify:` braucht. Empfehlung: wie geplant.

## Risiken & Rollback

Gering: Texte und Kommentare. Risiko ist falsche Doku durch Nachziehen ohne Codelesung; Gegenmittel: je Aussage die
Codestelle lesen. Die zwei Rust-Tests dürfen nur Lücken schließen und müssen in einer Gegenprobe fallen können.
Rollback: Revert des PR.

## Doku-Impact

Das Vorhaben besteht aus Doku. CHANGELOG nur, wo sichtbarer Text (Hook-Hinweis „UTC“) oder ein veralteter Satz (RDP
„Verbindung fehlgeschlagen“, R-0866) betroffen ist.

## Offene Fragen

Keine für Kevin. Verhaltensnahe Fragen, die beim Bau auftauchen (z. B. zeigt sich, dass der JoinHandle-Test einen
echten Fehler aufdeckt), werden gemeldet statt gebaut.
