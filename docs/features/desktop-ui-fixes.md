<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Desktop-UI: Ladefehler der Verbindungsliste, RDP-Bildschirmdaten, Sprachwahl, Löschen mit Rückfrage, Benachrichtigungs-Neustart, Visitor-Port-Prüfung

Stand des Codes: `origin/main@b1432223`. Alle `datei:zeile` beziehen sich auf diesen Stand. Ledger:
`tasks/desktop-ui-fixes.md`. Roadmap R-0658 (T1–T3), R-0659 (T4), R-0660 (T5–T7), R-0661 (T8), R-0663 (T9),
R-0585 (T10). Alle Änderungen liegen unter `apps/desktop/ui/` (dazu `CHANGELOG.md` und für T10 eine Doku-Seite);
keine Rust-Datei unter `apps/desktop/src-tauri/`.

## Problem / Motivation

1. **Ein gescheiterter Abruf leert die Verbindungsliste, und niemand sagt es (R-0658).** `reloadForMode`
   (`apps/desktop/ui/src/lib/stores/connections.ts:105-127`) setzt im `catch` die Liste auf `[]` und nur `error`
   (`:123-126`). Keine Komponente liest `error` oder `loading` des Stores (`connectionsStore` `:32`, `loading` `:34`;
   grep über `src/**/*.svelte` ohne Treffer). Die Seite „Verbindungen“ zeigt bei leerer Liste immer
   `connections.empty` („Noch keine Verbindungen angelegt“, `apps/desktop/ui/src/pages/Connections.svelte:246-249`),
   auch während des ersten Abrufs und nach einem Netzfehler; das Dashboard zeigt Nullen und `dashboard.empty`
   (`apps/desktop/ui/src/pages/Dashboard.svelte:34-51`, `:75-77`). Beide Seiten rufen beim Mount
   `loadForCurrentMode` (`Connections.svelte:26-28`, `Dashboard.svelte:21`), jeder Seitenwechsel ist also ein Abruf,
   und jeder gescheiterte leert die Liste, die eben noch zu sehen war. Ein Sync-Takt im Minutenabstand
   (`apps/desktop/ui/src/lib/stores/settings.ts:44-51`) leert sie bei jedem Aussetzer der Quelle.

2. **Der RDP-Start gibt keine Bildschirmdaten mit (R-0659).** `performConnect`
   (`apps/desktop/ui/src/lib/stores/connectFlow.ts:257-294`) ruft `openConnection`/`openConnectionStored` mit
   `client` `undefined` (`:270-271`); nichts in `src/` liest `window.screen` oder `devicePixelRatio`. Rust nimmt dann
   für „Eingepasst“ 1280x800 als Bildschirm (`apps/desktop/src-tauri/src/connection/rdp_logic.rs:128-141`, `/size:1088x720`),
   „Automatisch“ erkennt nie HiDPI (`hdpi_scale` gibt ohne `client` `None`, `:144-160`), „HiDPI“ setzt immer
   `/scale:180` (`apps/desktop/src-tauri/src/connection/rdp.rs:248-259`). Die bestehenden Tests pinnen den Fund:
   `client: undefined` in `apps/desktop/ui/src/lib/stores/connectFlow.test.ts:257`, `:311`, `:393`, `:407`, `:420`,
   `:437`. Der alte Plain-JS-Client gab die Daten mit (`getClientInfo`, `git show 4786c0a5^:desktop/src/platformApi.js`,
   Zeilen 185-191: `screenWidth: win.screen.width`, `screenHeight: win.screen.height`, `scaleFactor:
   win.devicePixelRatio || 1`); mit der Svelte-Migration ging das verloren. Rusts Tests nehmen dieselbe Form an
   (`rdp_logic.rs:325`: 1920x1080 bei Faktor 2.0 → `/scale:180`).

3. **Drei Rückfallregeln für die Sprache (R-0660).** Eine frische Installation hat `language: None`
   (`apps/desktop/src-tauri/src/models.rs:131`). Vor dem Laden gilt `detectBrowserLanguage`
   (`apps/desktop/ui/src/lib/i18n/index.ts:16-22`: Präfix der Browsersprache, sonst `de`), nach dem Laden
   `setLanguage(null)` → `en` (`:38-40`, aus `hydrate`, `apps/desktop/ui/src/lib/stores/session.ts:86`), im
   Einstellungsdialog `null` → `de` (`apps/desktop/ui/src/components/SettingsModal.svelte:92`), und die Vorgaben
   kennen eine vierte Form (`detectSystemLanguage`, `apps/desktop/ui/src/lib/models/settings.ts:15-18`). Folge auf
   einem deutschen System: die UI läuft englisch, der Dialog zeigt „Deutsch“, und jedes Speichern einer beliebigen
   Einstellung schaltet auf Deutsch (`SettingsModal.svelte:278-290` schreibt `language` mit).

4. **Löschen im Verbindungs-Editor ohne Rückfrage (R-0661).** `onDelete`
   (`apps/desktop/ui/src/components/ConnectionEditor.svelte:65-82`) entfernt sofort, im Server-Modus auf dem Server
   (`connections.ts:200-206` → `connectionsApi.remove`) und bei RDP samt gespeichertem Passwort (`:70-76`). Die
   Monitoring-Dialoge fragen vorher mit `confirmDialog` (`apps/desktop/ui/src/components/monitoring/AlertRuleModal.svelte:94-104`),
   ebenso Picker, Login und Einstellungen.

5. **Jedes Speichern der Einstellungen startet die Benachrichtigungen neu (R-0663).** `session` ist
   `derived(_state, ($s) => $s.session)` (`apps/desktop/ui/src/lib/stores/session.ts:52`); `derived` meldet einen
   Objektwert bei jeder Änderung von `_state` neu, auch wenn er derselbe ist (`safe_not_equal`,
   `node_modules/svelte/src/internal/client/reactivity/equality.js:13-17`, Svelte 5.56.2), und die Store-Anbindung
   einer Komponente reicht ihn als `mutable_source` weiter (`.../reactivity/store.js:39`, `:64`), die dieselbe Regel
   nimmt. Der Effekt in `apps/desktop/ui/src/components/AppShell.svelte:116-121` liest `$session` und läuft also nach
   `refreshSettings` (`session.ts:156-159`, gerufen von `saveSettings`, `settings.ts:84`) neu: `deactivateNotifications`
   stoppt den Stream, leert den Feed und setzt das Priming zurück (`apps/desktop/ui/src/lib/stores/notifications.ts:133-151`),
   `activateNotifications` startet neu (`:102`). Meldungen aus dieser Lücke kommen ohne OS-Benachrichtigung, der
   Feed flackert. Beleg (Probe, Node v22.23.1, `svelte/store` aus dem Worktree): ein `derived` über einen `writable`
   mit einem Sitzungsobjekt meldet nach einem Update, das nur `settings` ändert, zum zweiten Mal (Zähler 2 statt 1),
   dreimal identisch.

6. **Der Tunnel-Dialog prüft den Visitor-Port nicht (R-0585).** `validateTunnelForm`
   (`apps/desktop/ui/src/lib/models/frpTunnel.ts:96-103`) prüft Konfiguration, Name und lokalen Port, nicht
   `visitorPort`. Der Server nimmt nur 1–65535 (`apps/server/app/modules/frp/schemas.py:143-144`, `:248`, `:272`) und
   antwortet sonst mit 422; der Nutzer sieht erst diesen Fehler. Die Admin-Doku beschreibt den Bereich
   (`docs/admin/frp-tunnel.html:105`, EN `docs/en/admin/frp-tunnel.html:105`).

## Ziel & Nicht-Ziele

Ziel:
- Scheitert ein Abruf der Verbindungen, bleibt die Liste im Speicher stehen, wenn sie aus derselben Quelle stammt
  (Server: derselbe Server und Benutzer; Sync: dieselbe URL); sonst ist sie leer. „Verbindungen“ und Dashboard zeigen
  den Fehler mit „Erneut versuchen“; während des Ladens zeigt „Verbindungen“ „Lade…“ statt „Noch keine Verbindungen
  angelegt“ (T1–T3).
- Der RDP-Start gibt `client` mit Bildschirmbreite, -höhe (CSS-Pixel aus `window.screen`) und `devicePixelRatio` mit,
  wie der alte Client (T4).
- Eine Regel für die Sprache ohne gespeicherten Wert: die Systemsprache (`navigator.language` beginnt mit `de` →
  Deutsch, sonst Englisch), im Hydrate, in den Vorgaben und im Dialog (T5, T6); vor dem Laden nach Kevins Antwort (T7).
- „Löschen“ im Verbindungs-Editor fragt mit `confirmDialog` nach, wie die Monitoring-Dialoge; Escape während der
  Frage schließt den Editor nicht (T8).
- Der Benachrichtigungs-Effekt hängt an Server-URL und Benutzer, nicht am Sitzungsobjekt (T9).
- Der Tunnel-Dialog lehnt bei STCP einen Visitor-Port außerhalb 1–65535 (und einen nicht ganzzahligen) vor dem
  Speichern ab; ein leeres Feld bleibt erlaubt (T10).

Nicht-Ziele (YAGNI):
- **Kein Rückfall auf den Cache `connections.json`** (R-0658 nennt ihn als ungenutzt). Server-Modus: die Datei
  gehört dem zuletzt angemeldeten Benutzer des Workspace, das Abmelden lässt sie liegen (`session.ts:133-139`,
  `connections.ts:134-141`); ein Rückfall zeigte nach einem Benutzerwechsel ohne Netz fremde Verbindungen. Sync-Modus:
  wird die URL eines geschlossenen Workspace im Picker geändert, bleibt der Cache der alten URL liegen (kein Löschen in
  `apps/desktop/src-tauri/src/workspace.rs`); eine Abhilfe bräuchte Rust. Behalten wird nur die Liste dieses Prozesses.
- **Der Abruf je Seitenwechsel bleibt.** Im Server-Modus ist er der einzige Weg, die Liste aufzufrischen (kein Takt);
  während des Abrufs bleibt die Liste stehen (`connections.ts:111`), nach T1 auch nach einem Fehler.
- **`syncNow(true)` bleibt ohne Aufrufer** (`settings.ts:53-64`, nur `settings.test.ts:100-113`): fremder toter Code,
  hier erwähnt, nicht gelöscht. „Erneut versuchen“ ist kein „Jetzt synchronisieren“-Knopf.
- `load()` (Cache bei fehlenden Einstellungen, `connections.ts:85-96`) behält sein Verhalten.
- R-0659: Rust bleibt. Ob `/size` von xfreerdp physische Pixel erwartet, während `fit_window_size` mit CSS-Pixeln
  rechnet (`rdp_logic.rs:128-141`), ist nicht verifiziert; die UI hält den Vertrag, den Rust und der alte Client
  annehmen. SSH und Web bekommen kein `client` (Rust nutzt es nur für RDP unter Unix, `rdp_logic.rs:127`, `:143`).
- R-0660: `language` wird beim Start nicht gespeichert; bis zum ersten Speichern bleibt `null`, und Rust nimmt dann
  für die RDP-Tastatur US (`apps/desktop/src-tauri/src/connection/rdp.rs:331-338`). Eine Abhilfe bräuchte Rust oder
  ein Schreiben beim Start; nicht Teil der Zeile.
- R-0663: Die Reihenfolge von `stopNotificationStream` (nicht abgewartet, `notifications.ts:147`) und dem nächsten
  Start bleibt. Nach T9 läuft der Effekt nur bei einem Wechsel von Server oder Benutzer; `AppShell` ist erst nach dem
  Login gemountet (`apps/desktop/ui/src/App.svelte:28-31`), Abmelden lädt das Fenster neu (`settings.ts:102-115`), der
  Verdacht hat damit keinen erreichbaren Weg mehr. Andere Effekte, die `$sessionStore` lesen (Monitoring-Charts),
  laden nach dem Speichern neu; nicht Teil der Zeile.
- R-0585: keine Bereichsprüfung des lokalen Ports (der Server nimmt `IntColumn`, `schemas.py:245`), keine
  `min`/`max`-Attribute am Eingabefeld.
- R-0661: Die Zwei-Klick-Löschknöpfe der Infrastruktur-Dialoge (`ServerModal`, `TunnelModal`, `PlaybookModal`,
  `ServerConnectionModal`) bleiben.

## Betroffene Komponenten & Dateien

| Task | Komponente | Dateien |
|---|---|---|
| T1 | desktop-ui | `apps/desktop/ui/src/lib/stores/connections.ts`, `apps/desktop/ui/src/lib/stores/connections.reload.test.ts` (neu), `apps/desktop/ui/src/lib/stores/settings.ts` (Kommentar), `CHANGELOG.md` |
| T2 | desktop-ui | `apps/desktop/ui/src/components/ConnectionsLoadError.svelte` (neu), `apps/desktop/ui/src/pages/Connections.svelte`, `apps/desktop/ui/src/lib/i18n/dictionaries.ts`, `apps/desktop/ui/src/pages/Connections.load.test.ts` (neu), `CHANGELOG.md` |
| T3 | desktop-ui | `apps/desktop/ui/src/pages/Dashboard.svelte`, `apps/desktop/ui/src/pages/Dashboard.load.test.ts` (neu), `CHANGELOG.md` |
| T4 | desktop-ui | `apps/desktop/ui/src/lib/stores/connectFlow.ts`, `apps/desktop/ui/src/lib/stores/connectFlow.test.ts`, `CHANGELOG.md` |
| T5 | desktop-ui | `apps/desktop/ui/src/lib/i18n/index.ts`, `apps/desktop/ui/src/lib/models/settings.ts`, `apps/desktop/ui/src/lib/i18n/i18n.test.ts`, `CHANGELOG.md` |
| T6 | desktop-ui | `apps/desktop/ui/src/components/SettingsModal.svelte`, `apps/desktop/ui/src/components/SettingsModal.save.test.ts`, `CHANGELOG.md` |
| T7 | desktop-ui | `apps/desktop/ui/src/lib/i18n/index.ts`, `apps/desktop/ui/src/lib/i18n/i18n.test.ts`, `CHANGELOG.md` |
| T8 | desktop-ui | `apps/desktop/ui/src/components/ConnectionEditor.svelte`, `apps/desktop/ui/src/components/ConnectionEditor.delete.test.ts` (neu), `apps/desktop/ui/src/lib/i18n/dictionaries.ts`, `CHANGELOG.md` |
| T9 | desktop-ui | `apps/desktop/ui/src/components/AppShell.svelte`, `apps/desktop/ui/src/components/AppShell.notifications.test.ts` (neu), `CHANGELOG.md` |
| T10 | desktop-ui | `apps/desktop/ui/src/lib/models/frpTunnel.ts`, `apps/desktop/ui/src/lib/models/frpTunnel.test.ts`, `apps/desktop/ui/src/lib/i18n/dictionaries.ts`, `docs/admin/frp-tunnel.html`, `docs/en/admin/frp-tunnel.html`, `CHANGELOG.md` |

Keine Datei steht auf `scripts/dev/review-risk.txt` (`bridge/types.ts` bleibt unverändert): kein `security`-Prüfer.

## Datenmodell / API / Migrationen

Keine Migration, keine Route, kein Tauri-Command, kein Schema. `ClientInfo` (`apps/desktop/ui/src/lib/bridge/types.ts:91-95`,
Rust `models.rs:200-206`) und die Signaturen von `openConnection`/`openConnectionStored`
(`apps/desktop/ui/src/lib/bridge/index.ts:194-220`) bestehen schon; T4 füllt nur das Argument. `settings.json`/`prefs.json`
bekommen weiter `de` oder `en` (nach T6 beim Speichern die aufgelöste Sprache statt eines falschen `de`). Neue
i18n-Schlüssel (DE+EN, die Paritäts- und Unbenutzt-Tests in `src/lib/i18n/i18n.test.ts` gelten): `connections.loadFailed`,
`connections.loadFailed.kept` (T2), `editor.deleteConfirm` (T8), `infra.tun.validation.visitorPortRange` (T10).

## Externe Integrationen

- Svelte 5.56.2 (`node_modules/svelte`, gelesen 2026-10-22): `derived`/`writable` melden einen Objektwert immer neu
  (`safe_not_equal`); `$derived` im Runes-Modus vergleicht mit `===` und hält gleiche Strings zurück. Darauf baut T9.
- `Screen.width`/`height` und `Window.devicePixelRatio` (CSSOM View): Größe in CSS-Pixeln und Verhältnis zu
  Geräte-Pixeln. Nicht geprüft, was WebKitGTK unter Wayland mit gebrochener Skalierung liefert (Restrisiko T4).
- Sonst keine (keine FRP-, VictoriaMetrics- oder Server-Schnittstelle ändert sich).

## Trade-offs & Alternativen

1. **Welche Liste nach einem Fehler bleibt (T1).** (a) Die Liste im Speicher, wenn ihr letzter erfolgreicher Abruf
   dieselbe Quelle hatte (Schlüssel aus Art, Server-URL und Benutzer bzw. Sync-URL), sonst `[]` — **Empfehlung**: löst
   den Fund, kann nie eine fremde Liste zeigen (die Vorsicht von `loadGen`, `connections.ts:78-83`). (b) Rückfall auf
   `connections.json` — siehe Nicht-Ziele. (c) Immer behalten — zeigte nach einem Wechsel der Quelle die alte Liste.
2. **Fehleranzeige als eigene Komponente (T2, T3).** Ein Banner mit Text und „Erneut versuchen“ wie
   `MonitoringOverview.svelte:78-83` (CSS `:247-261`), als `ConnectionsLoadError.svelte`, weil zwei Seiten ihn zeigen.
   Alternative: Statuszeile (`reportError`) — verschwindet und sagt nichts über die leere Liste.
3. **Pixel-Einheit von `ClientInfo` (T4).** CSS-Pixel plus `devicePixelRatio` — **Empfehlung**, der Vertrag des alten
   Clients und der Rust-Tests. Alternative: Geräte-Pixel (`screen.width * devicePixelRatio`) — änderte die Deutung
   von Rusts Schwellen (`rdp_logic.rs:150-158`) ohne Rust-Änderung.
4. **Wo die Sprachregel liegt (T5).** In `src/lib/i18n/index.ts` (`systemLanguage`, `resolveLanguage`), weil
   `models/settings.ts` schon `$lib/i18n` importiert (`:8`); umgekehrt entstünde ein Zyklus. Eine ungültige gespeicherte
   Sprache (nur von Hand in `prefs.json` möglich) gilt wie `null`.
5. **Rückfrage (T8).** `confirmDialog` mit `confirmLabel` „Löschen“, wie `AlertRuleModal.svelte:94-104` und wie die
   Zeile es vorgibt; der Escape-Schutz `asking` wie `SettingsModal.svelte:72-78`, `:182-186`, `:342`, weil das Overlay
   des Editors Escape selbst behandelt (`ConnectionEditor.svelte:111`). Alternative: der Zwei-Klick-Knopf der
   Infrastruktur-Dialoge — die Zeile nennt `confirmDialog`.
6. **Ort des Fixes (T9).** (a) In `AppShell` ein `$derived`-Schlüssel aus `serverUrl` und `username` — **Empfehlung**,
   die Abhilfe der Zeile, eine Datei. (b) `session` in `session.ts` nur bei neuer Identität melden — änderte das
   Verhalten für rund 35 Leser von `$session`; nicht nötig für den Fund.
7. **Prüfung des Visitor-Ports (T10)** in `validateTunnelForm` mit `Number.isInteger` und 1–65535 wie
   `models/connection.ts:41-44`; nur bei STCP, weil `formToInput` den Port bei HTTPS nullt (`frpTunnel.ts:89`).

## Risiken & Rollback

- T1: Eine behaltene Liste kann veraltet sein; das Banner sagt es (`connections.loadFailed.kept`). Ein Klick startet
  eine Verbindung aus dieser Liste wie bisher aus einer frischen.
- T4: Ändert die xfreerdp-Argumente unter Linux bei „Eingepasst“ (`/size` aus der echten Bildschirmgröße statt
  1088x720) und bei „Automatisch“/„HiDPI“ (`/scale` nach Faktor). Verifiziert durch Unit-Tests auf die Argumente der
  Bridge und den RDP-Start der GUI-E2E im Sammellauf (`desktop_e2e_connect.sh`, `rdp-connect.live.js`, ohne HiDPI);
  auf einem echten HiDPI-Bildschirm nicht verifiziert (die Zeile: „Laufzeit nicht geprüft“). Windows unberührt
  (`fit_window_size`/`hdpi_scale` nur unter Unix).
- T5/T6: Nutzer auf einem deutschen System ohne gespeicherte Sprache sehen nach dem Update Deutsch statt Englisch —
  das ist der Fix.
- T8: Kein E2E-Spec löscht über den Verbindungs-Editor (`connection-crud.live.js` nutzt `ServerConnectionModal`).
- T10: `tunnel-create.live.js` lässt den Visitor-Port leer und bleibt gültig.
- `CHANGELOG.md` ändern auch die parallelen Vorhaben; vor jedem Push `origin/main` hineinmergen.
- Rollback: jede Task ein eigener Commit ohne Datenänderung; Revert genügt.

## Doku-Impact

CHANGELOG (Fixed) für T1–T9, (Changed) für T10, umlautfrei. T10 zusätzlich ein Satz in `docs/admin/frp-tunnel.html:105`
und `docs/en/admin/frp-tunnel.html:105`: der Tunnel-Dialog des Desktop-Clients lehnt einen Visitor-Port außerhalb
1–65535 schon vor dem Speichern ab. Sonst keine: weder Spracheinstellung noch Ladeanzeige noch RDP-Fenstergröße sind
in `docs/` beschrieben (gesucht: `docs/developer/desktop.html`, `docs/admin/*.html`, Stichwörter Sprache/Systemsprache,
HiDPI, Eingepasst, `connections.json`).

## Offene Fragen

1. **T7 — Systemsprache außer Deutsch/Englisch vor dem Laden der Einstellungen.** Heute gilt dort Deutsch
   (`detectBrowserLanguage`), nach dem Laden Englisch. Sichtbar ist das nur bei einer anderen Systemsprache: „Lade…“
   vor dem Laden und die ganze UI, wenn das Laden der Einstellungen scheitert (`session.ts:92-94`). Optionen: (A)
   Englisch wie nach dem Laden, eine Regel — **Empfehlung**: entspricht dem Zustand nach dem Laden heute und nach T5;
   die Zeile verlangt eine Regel. (B) Deutsch wie heute — T7 entfällt (`[~]`), es bleiben zwei Regeln, die sich nur
   bei anderen Systemsprachen unterscheiden. (C) Deutsch für jede andere Systemsprache überall — änderte auch T5 und das
   Verhalten nach dem Laden (heute Englisch). **Antwort Kevin 2026-10-22: (A)**, gebaut in T7.
2. **Restrisiko T4 (zur Kenntnis, kein Gate):** HiDPI und gebrochene Skalierung unter Wayland sind mangels Bildschirm
   auf den Pool-VMs nicht prüfbar; Beleg sind die Unit-Tests auf die Argumente, Rusts Tests der Abbildung und der
   RDP-Start im Sammellauf.
