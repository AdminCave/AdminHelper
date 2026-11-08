<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-rdp-1 — Eingebettetes RDP: Pin immer, Stufe 2 Tab

Roadmap R-1141, R-1098 (Zug `tasks/kern-rdp-1.md`). Stand `origin/main@aa28e01a6`, IronRDP an der gepinnten Revision
`f96f664`. Bauplan: `docs/features/arch-rdp-embedded.md` („Bauplan für R-1075“, Stufe 2; Bedingungen 3–7), Backend:
`docs/features/arch-rdp-backend.md` (Stufe 1, Offene Frage 1). Der Bau beginnt nach dem Merge von #418
(`feature/kern-rdp-3` ändert `rdp_embedded/mod.rs`, `session.rs` und `docs/developer/desktop.html`).

## Problem / Motivation
- **R-1141:** IronRDP ruft den Prüf-Callback erst, wenn seine strenge Prüfung (Wurzeln der Plattform, Servername)
  scheitert (`crates/ironrdp-tls/src/rustls_verifier.rs:89`, `CallbackVerifier`). Ein Zertifikat, das eine
  Plattform-CA für den Hostnamen ausgestellt hat, gilt deshalb ohne Pin und ohne Dialog
  (`apps/desktop/src-tauri/src/rdp_embedded/tofu.rs:7`). Kevin hat das für Stufe 1 hingenommen und R-1141 vor Stufe 2
  gesetzt (2026-11-05); Weg (c): Upstream-PR an IronRDP und bis zum Upstream-Release eine eigene Fork-Revision als
  Pin (Kevin 2026-11-08).
- **R-1098:** Das Backend der eingebetteten Sitzung steht (Stufe 1, R-1097), aber keine Oberfläche ruft es auf
  (`docs/developer/desktop.html:258`). RDP öffnet nur der Client des Betriebssystems.

## Ziel & Nicht-Ziele
Ziel:
- **Pin immer (R-1141).** Eine additive Option in `ironrdp-tls`, mit der der Callback jedes Leaf-Zertifikat sieht,
  auch nach bestandener strenger Prüfung; bestehende Signaturen bleiben. Upstream-PR gegen `Devolutions/IronRDP`
  `master` nach den Regeln des Projekts (`AGENTS.md`, `STYLE.md`, Tests in `ironrdp-testsuite-*`). Der Desktop pinnt
  alle `ironrdp-*` auf eine Revision im Fork `AdminCave/IronRDP` (f96f664 plus genau dieser Patch) und nutzt die
  Option: ohne Pin kommt die Phase `certificate`, gleich ob eine CA das Zertifikat ausgestellt hat. `trust_cert`
  bleibt „ohne Dialog annehmen“.
- **Tab (R-1098).** Eine RDP-Sitzung öffnet als Tab in der Sitzungs-Tableiste aus R-1069 (`SessionTabs.svelte`,
  Store `lib/stores/terminals.ts`):
  - Bild über den Frame-WebSocket (Token, Quittungen, 14-Byte-Kopf; `desktop.html` „Bild-WebSocket“) auf einem
    Canvas mit WebGL, Rückfall 2d; das feste Desktop-Format 1280×720 wird eingepasst (dynamische Auflösung ist
    Stufe 4).
  - Eingabe: Scancodes aus `KeyboardEvent.code`, Maus und Rad in Desktop-Koordinaten; Tastatur-Fang der fokussierten
    Sitzung, Strg+Alt+Pos1 gibt frei (Bedingung 6).
  - Phasen verbinden/verbunden/neu verbinden/getrennt/fehlgeschlagen aus dem Event `rdp-session`; Trennen und Neu
    verbinden; der Zertifikatsdialog bei `certificate` (Fingerprint, Grund) ruft `rdp_trust_certificate` und startet
    neu.
  - Menü: Strg+Alt+Entf, Screenshot (PNG, Speichern-Dialog; `dialog:allow-save` ist erlaubt), Verbindungsinfo.
  - Statuszeile: Auflösung, fps, Mbit/s; Codec und RTT nur, wenn die Sitzung sie kennt (RTT aus
    `RdpOutputEvent::NetworkCharacteristics`), sonst „—“.
  - Leistungsprofil: die globale `rdp_performance_profile` (`models.rs:264`) wirkt auch eingebettet, über
    `ConfigBuilder::with_performance_flags`.
- **Einstellung `rdp_client`** in `Settings` (`models.rs:245`, `#[serde(default)]`): AdminHelper oder OS-Client,
  Standard OS-Client bis R-1090 (Bedingung 4). In den Einstellungen unter *RDP*; der Pfeil am Knopf *Verbinden* wählt
  den Client nur für diesen Start, wie bei SSH (`ConnectButton.svelte`).
- **Rückfall:** lehnt `rdp_session_start` mit `ERR_RDP_OS_CLIENT` ab (Gateway, Drucker; R-1163), startet der Aufrufer
  den Client des Betriebssystems und sagt das in der Statusleiste.

Nicht-Ziele:
- Dynamische Auflösung, Zoom, Vollbild, HiDPI (Stufe 4, R-1100); Abdocken, Multi-Monitor (Stufe 5, R-1101/R-1102);
  Kanal-Schalter im Tab (Stufe 3).
- AdminHelper als Standard (R-1090).
- Tabs des letzten Starts wieder öffnen für RDP.

## Betroffene Komponenten & Dateien
- **IronRDP (Fork, Upstream-PR):** `crates/ironrdp-tls/src/rustls_verifier.rs`, `src/lib.rs`, ein Test in
  `ironrdp-testsuite-*`; dazu der Weg der Option durch `ironrdp-client` (`src/config.rs:1485`
  `with_certificate_validation`, `:1497` Callback), wenn sie dort gesetzt wird.
- **Desktop (Rust):** `Cargo.toml` (Pin), `Cargo.lock`, `src/rdp_embedded/tofu.rs`, `session.rs` (Callback-Option,
  Statistik, Leistungsprofil, Screenshot), `mod.rs` (neue Befehle), `src/main.rs` (`generate_handler!`, `:236`),
  `src/capabilities.rs`, `src/models.rs` (`rdp_client`), `src/connection/rdp.rs:441` (`performance_args`, als Vorbild
  der Abbildung).
- **Desktop-UI:** `lib/bridge/` (Befehle, Typen, `types.parity.test.ts`), neue Bibliothek `lib/rdp/` (WebSocket,
  Renderer, Tastatur, Maus), Store `lib/stores/terminals.ts`, `lib/stores/connectFlow.ts` (`handleRdpAuth` `:243`,
  `performConnect`), Komponenten `components/terminal/` (neuer `RdpSession.svelte`, `SessionTabs.svelte`,
  `ConnectButton.svelte`), `components/settings/RdpSection.svelte`, `lib/i18n/dictionaries.ts`.
- **E2E:** eine Live-Spec unter `apps/desktop/e2e/test/specs/` gegen den xrdp-Container aus `scripts/tests/xrdp-gfx`.
- **Doku:** `docs/developer/desktop.html` und `docs/en/developer/desktop.html` (Abschnitt „Eingebettetes RDP“),
  `docs/admin/index.html` und `docs/en/admin/index.html` (Einstellungen, RDP-Tab), `changelog.d/kern-rdp-1.md`,
  `docs/features/arch-rdp-backend.md` (Offene Frage 1 erledigt), `THIRD_PARTY_LICENSES.md` nur, wenn sich die Quelle
  der `ironrdp-*` darin niederschlägt.

## Datenmodell / API / Migrationen
- `Settings.rdp_client` (`"embedded" | "os"`, Default `os`), Wire-Vertrag Backend ↔ UI (`models.rs`, `types.ts`,
  Parity-Test; Risikopfad). Alte Einstellungsdateien ohne das Feld lesen sich als `os`.
- Neue Tauri-Befehle für Strg+Alt+Entf, Screenshot und Verbindungsinfo bzw. neue Nachrichten auf dem Frame-WebSocket
  (Statistik als Text-JSON); die Form legt T2 fest und dokumentiert sie in `desktop.html`.
- Keine Server-, Web- oder Agent-Änderung, keine Migration.

## Externe Integrationen
- IronRDP `f96f664` (<https://github.com/Devolutions/IronRDP>): `rustls_client_config`/`server_cert_verifier`,
  `CertificateValidationCallback` (`ironrdp-tls/src/lib.rs:59`), `ConfigBuilder::with_performance_flags`
  (`ironrdp-client/src/config.rs:1522`), `RdpOutputEvent::NetworkCharacteristics`. Upstream-Regeln: `AGENTS.md`
  (kein Bezug auf Planungsdokumente in Commits und PR-Text, `UNTESTED:`-Kommentare, Tests in den Testsuiten).
  Upstream hat für „Callback immer fragen“ keinen PR (nachgesehen 2026-11-08; letzte Änderung am Verifier #1811).
- Cargo-Git-Abhängigkeiten: alle `ironrdp-*` müssen aus derselben Quelle kommen, sonst baut Cargo zwei Kopien;
  `[patch."https://github.com/Devolutions/IronRDP"]` auf den Fork oder ein Wechsel aller URLs (Wahl in T1).
- WebGL 1 in WebKitGTK und WebView2; ohne Kontext 2d. `KeyboardEvent.code` → Set-1-Scancodes (mit E0-Präfix).

## Trade-offs & Alternativen
- **Option upstream statt eigener rustls-Verifier im Desktop:** IronRDP nimmt keinen fremden Verifier entgegen; ein
  eigener hieße einen größeren Fork. Die additive Option ist klein und upstream-fähig. Empfohlen (Kevin: Weg (c)).
- **Statistik über den Frame-WebSocket statt Event:** dieselbe Verbindung wie das Bild, kein zweiter Kanal; Wahl in T2.
- **Canvas mit WebGL statt `putImageData`:** Bedingung 3 und T3 der Arch-Spec; 2d bleibt als Rückfall.
- **Ein Tab-Store für SSH und RDP:** die Tableiste aus R-1069 bleibt eine; RDP-Sitzungen bekommen dort eine eigene
  Art statt eines zweiten Stores.

## Risiken & Rollback
- **Fork-Abhängigkeit:** solange der Upstream-PR offen ist, hängt der Desktop an `AdminCave/IronRDP`. Der Fork trägt
  nur f96f664 plus den Patch; nach dem Upstream-Merge wechselt der Pin zurück (Folgezeile).
- **Pin immer** fragt bei CA-Zertifikaten einmal mehr; das ist der Zweck. Fehlerfall: Sitzung endet mit `certificate`
  statt zu verbinden, nie umgekehrt (Test).
- **Tastatur-Fang:** eine gefangene Tastatur, die nicht freigibt, sperrt die App; Strg+Alt+Pos1 und Fokusverlust
  geben frei (Test).
- **Standard bleibt OS-Client:** wer nichts umstellt, merkt nichts.
- Rollback per Revert der Task-Commits; die Einstellung ist additiv (`serde(default)`), ein älterer Desktop ignoriert
  das Feld.

## Doku-Impact
`docs/developer/desktop.html` DE+EN (eingebettetes RDP: Pin immer, Befehle, WebSocket-Nachrichten, Tab),
`docs/admin/index.html` DE+EN (Einstellung *Client für RDP*, Bedienung des RDP-Tabs), `changelog.d/kern-rdp-1.md`.

## Offene Fragen
Keine. Entschieden (Kevin 2026-11-08):
1. **Start ohne gespeichertes Passwort:** Der Passwort-Dialog fragt, `rdp_session_start` nimmt das getippte Passwort
   einmalig an (wie der OS-Client-Weg, `connectFlow.ts:285`; das Passwort geht schon heute vom Webview nach Rust).
   Gespeichert wird es nur, wenn der Nutzer *Merken* wählt. Betrifft T6.
2. **Strg+Alt+Entf gegen Windows** (Bedingung 6): eine Probe auf einem Windows-Runner im privaten Wegwerf-Repo von
   R-1092, Ergebnis nur privat. Betrifft T9.
