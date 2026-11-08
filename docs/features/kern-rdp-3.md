<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-rdp-3 — Eingebettetes RDP: Gateway, Drucker und NLA; Windows-Probe

Roadmap R-1163, R-1092 (Zug `tasks/kern-rdp-3.md`). R-1100 (Stufe 4 Anzeige) fährt nicht mit: sie hängt an R-1098,
das noch nicht gemergt ist, und ist nach `tasks/kern-rdp-4.md` verschoben. Stand `origin/main@15084d08`, IronRDP an
der gepinnten Revision `f96f664`.

## Problem / Motivation
- **R-1163:** Die eingebettete Sitzung liest von `options.rdp` nur `audio` und `drives`. `gateway`, `printers` und
  `nla` wirken nur beim Client des Betriebssystems (`docs/developer/desktop.html:261`): `config()` setzt
  `with_credssp(true)` und `with_printers(false)` fest (`apps/desktop/src-tauri/src/rdp_embedded/session.rs:439`,
  `:451`), ein Gateway kennt sie nicht. Eine Verbindung hinter einem RD-Gateway erreicht sie damit nicht, eine mit
  NLA aus verlangt trotzdem CredSSP, eine mit Druckern bekommt keine.
- **R-1092:** Die Probe aus R-1074 T4 endete gegen Windows im Kanal-Lauf mit einem Absturz (Einzelheiten nur
  privat). Bis das geklärt ist, bleibt Audio unter Windows aus (Bedingung 12 aus `docs/features/arch-rdp-embedded.md`).

## Ziel & Nicht-Ziele
Ziel:
- **Gateway** (Kevin 2026-11-08): Nennt die Verbindung ein Gateway, startet keine eingebettete Sitzung;
  `rdp_session_start` lehnt mit dem neuen Code `ERR_RDP_OS_CLIENT` ab, und der Aufrufer startet den Client des
  Betriebssystems. Den Aufrufer gibt es erst mit Stufe 2 (R-1098, Split-Button und `rdp_client`); bis dahin ruft
  keine Oberfläche `rdp_session_start` auf.
- **Drucker:** `printers: true` lehnt ebenso mit `ERR_RDP_OS_CLIENT` ab: Die eingebettete Sitzung bringt keinen
  Druckerkanal, der Client des Betriebssystems schon. Gleiche Regel wie beim Gateway (Entscheidung der Session).
- **NLA:** `nla: false` startet die eingebettete Sitzung ohne CredSSP (TLS allein), wie `/sec:tls` und
  `enablecredsspsupport:i:0` beim Client des Betriebssystems; ungesetzt oder `true` bleibt CredSSP an.
- **R-1092:** Die Probe läuft in einem privaten Wegwerf-Repo unter `AdminCave` auf einem Windows-Runner
  (Kevin 2026-11-06, bestätigt 2026-11-08), reproduziert den Absturz und grenzt den Code ein, in dem er entsteht.
  Ergebnis, Logs und gegebenenfalls ein Mail-Entwurf an den Hersteller nur unter `tasks/private/`; Kevin schickt ab.
  Nach dem Lauf wird das Repo gelöscht.

Nicht-Ziele:
- Gateway oder Drucker in der eingebetteten Sitzung selbst bauen.
- Der Rückfall in der Oberfläche (kommt mit R-1098).
- Audio unter Windows freischalten (braucht eine Abnahme auf einem Windows mit Audiogerät, Bedingung 12).

## Betroffene Komponenten & Dateien
- Desktop (Rust): `apps/desktop/src-tauri/src/rdp_embedded/mod.rs` (`prepare()`: Ablehnung, `nla` in den
  `Target`), `src/rdp_embedded/session.rs` (`Target`, `config()`), `src/error.rs` (Variante und Code).
- Doku: `docs/developer/desktop.html:199` und `:261`, `docs/en/developer/desktop.html` (dieselben Absätze),
  `changelog.d/kern-rdp-3.md`.
- Probe: nur das private Wegwerf-Repo und `tasks/private/spikes/arch-rdp-embedded/`; im Baum nur der Kommentar am
  Windows-Gate von `audio_mode()` (`session.rs:412`), neutral.

## Datenmodell / API / Migrationen
Kein Feld, keine Migration, kein neuer Tauri-Befehl. Neu ist der Ablehnungscode `ERR_RDP_OS_CLIENT` von
`rdp_session_start` (`AppError`, Vertrag in `docs/developer/desktop.html:199`); `message` nennt den Grund
(Gateway oder Drucker).

## Externe Integrationen
- IronRDP `f96f664`: `ConfigBuilder::with_credssp(false)` verbindet mit TLS ohne CredSSP; die Probe aus R-1074 T4
  lief so gegen Windows (`credssp: false`, Anmeldung erfolgreich). Kein Gateway-Client (RD-Gateway, MS-TSGU) im
  Client-Crate dieser Revision; vor der Task im Quelltext nachsehen.
- GitHub Actions `windows-latest` (Windows Server 2025, TermService an) für die Probe, wie in R-1074 T4.

## Trade-offs & Alternativen
- **Ablehnen mit Code statt still mit dem Client des Betriebssystems starten:** Der Rückfall gehört dem Aufrufer,
  der weiß, welchen Client der Nutzer gewählt hat (R-1098); das Backend startet keinen zweiten Client hinter dem
  Rücken des Webviews. Empfohlen.
- **Drucker wie Gateway** statt sie zu ignorieren: Ein still fehlender Drucker wäre ein Fehler ohne Meldung.

## Risiken & Rollback
- NLA aus schwächt die Anmeldung; das wählt der Nutzer in der Verbindung, wie beim Client des Betriebssystems.
  Das Zertifikat prüft die Sitzung weiter wie bisher (Pin bzw. CA).
- Die Probe läuft außerhalb dieses Repos; im Lauf liegen keine Passwörter (im Runner erzeugt und maskiert, wie in
  T4). Das Repo bleibt privat und wird danach gelöscht.
- Rollback per Revert der Task-Commits; Daten ändern sich nicht.

## Doku-Impact
`docs/developer/desktop.html` DE+EN (Abschnitt „Eingebettetes RDP (Backend)“ und der Fehlervertrag),
`changelog.d/kern-rdp-3.md`.

## Offene Fragen
Keine. Gateway: Kevin 2026-11-08; Drucker und NLA leitet die Session aus derselben Regel bzw. dem Verhalten des
Clients des Betriebssystems ab und nennt das am Gate.
