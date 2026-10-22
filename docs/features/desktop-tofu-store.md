<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Desktop: Zertifikat-Pin erst gespeichert, dann vertraut; Windows-Lesefehler; Rückfrage beim Pin-Reset

Stand des Codes: `origin/main@b1432223`. Alle `datei:zeile` beziehen sich auf diesen Stand. Ledger:
`tasks/desktop-tofu-store.md`. Härtung (Kevin 2026-10-22).

## Problem / Motivation

Mit „Selbstsignierte Zertifikate erlauben“ pinnt der Desktop beim ersten Verbinden den SHA-256 des Server-Zertifikats
und nimmt danach nur noch genau dieses an (`apps/desktop/src-tauri/src/tofu.rs:5-24`). Die Entwickler-Doku beschreibt
den Pin als im Schlüsselbund abgelegt: `docs/developer/desktop.html:242` — „Beim ersten Verbinden wird er erfasst und
im OS-Keyring abgelegt (Key <code>tofu|cert|&lt;host:port&gt;</code>, …), plus In-Memory-Cache, damit der
Enforce-Pfad nicht pro Request den Keyring trifft.“ Drei Stellen weichen davon ab:

1. **Ein Pin, der sich nicht speichern lässt, gilt trotzdem.** `KeyringPinStore::load_or_store`
   (`tofu.rs:158-186`) ruft bei einem ersten Verbinden `keyring_write` (`:182`) und legt den Fingerprint danach in den
   Prozess-Cache (`:183`). `keyring_write` verwirft den Fehler von `keyring_store::set` (`:200-202`). Scheitert das
   Speichern, vertraut der Prozess dem Zertifikat aus dem Cache bis zu seinem Ende, und der nächste Start pinnt neu,
   was der Server dann vorlegt. Ein Lesefehler wird schon heute abgelehnt (`:167-171`, Test `:408-413`), aber mit dem
   Text eines Zertifikatswechsels (`ERR_TOFU_PIN_MISMATCH`, `:255-260`); der Login bietet daraufhin „Gepinntes
   Server-Zertifikat zurücksetzen“ an (`apps/desktop/ui/src/components/Login.svelte:72`), was bei einem nicht
   lesbaren Schlüsselbund nichts löst.
   Die Suite zeigt Punkt 1 schon heute: Die beiden Session-Tests über einen selbstsignierten Server
   (`apps/desktop/src-tauri/src/session.rs:1224-1255`, `:1257-1290`) bauen den Pinning-Client
   (`build_client(server_url, true)`, `:1220`) und laufen `multi_thread`; der Handshake läuft auf einem tokio-Worker,
   wo der thread-lokale Test-Schlüsselbund fehlt (`apps/desktop/src-tauri/src/keyring_store.rs:87-90`), `set`
   scheitert (`:40-42`), `try_get` liefert `Ok(None)` (`:65-67`). Die Tests sind grün, weil der Pin nur im Cache gilt.

2. **Windows: ein Lesefehler gilt als „kein Eintrag“.** `os_try_get` unter Windows
   (`keyring_store.rs:182-190`) macht aus jedem Fehler von `windows_read_credential`
   (`apps/desktop/src-tauri/src/password.rs:1076-1107`, prüft den Fehlercode nicht) ein `Ok(None)`. Der Kommentar
   (`keyring_store.rs:184-186`) sagt, `CredReadW` könne „nicht gefunden“ nicht sauber von einem Lesefehler trennen;
   `windows_generic_read` (`password.rs:1034-1069`) tut genau das (`ERROR_NOT_FOUND` → `Ok(None)`, sonst `Err`,
   `:1056-1063`). Folgen: Beim Zertifikat-Pin wird ein Lesefehler zum ersten Verbinden, der neue Pin überschreibt den
   gespeicherten; `enrollment::holds_identity` (`apps/desktop/src-tauri/src/enrollment.rs:242-254`) meldet „keine
   Identität“, obwohl seine Doku sagt: „A keyring that does not answer is an error, as then no one can tell.“

3. **Die Einstellungen setzen den Pin ohne Rückfrage zurück.** `onResetPin`
   (`apps/desktop/ui/src/components/SettingsModal.svelte:157-171`) ruft `resetServerCertPin` direkt. Der Login fragt
   vor demselben Schritt mit `login.resetPin.confirmMitm` (`Login.svelte:95-98`), die Einstellungen vor dem
   Zurücksetzen der Geräte-Identität mit `settings.resetDeviceId.confirm` (`SettingsModal.svelte:182-187`). Nach dem
   Zurücksetzen nimmt der nächste Abruf (Sync-Intervall, Benachrichtigungen) das dann vorgelegte Zertifikat ohne
   weiteren Schritt des Nutzers als neuen Pin.

## Ziel & Nicht-Ziele

Ziel:
- Ein erster Kontakt wird nur angenommen, wenn der Pin im Schlüsselbund gespeichert ist. Lässt er sich nicht lesen
  oder nicht speichern, lehnt der Verifier ab, ohne zu pinnen, mit einem eigenen Text, der den Schlüsselbund nennt
  und nicht `ERR_TOFU_PIN_MISMATCH` trägt. Der Prozess-Cache hält nur gespeicherte Pins.
- Unter Windows unterscheidet `keyring_store::try_get` „kein Eintrag“ (`ERROR_NOT_FOUND`) von jedem anderen Fehler
  des `CredReadW`.
- Die Einstellungen fragen vor dem Pin-Reset mit demselben Text wie der Login.

Nicht-Ziele (YAGNI):
- **`forget_pin` verwirft den Fehler von `keyring_delete`** (`tofu.rs:204-206`, `:330-339`): Schlägt das Löschen
  fehl, bleibt der alte Pin im Schlüsselbund, der nächste Start lehnt weiter ab (kein Vertrauen in ein neues
  Zertifikat); nur die Erfolgsmeldung der UI stimmt dann nicht. Gehört als eigene BUG-Zeile in die Roadmap, nicht in
  dieses Paket.
- Keine Verlagerung der Schlüsselbund-Zugriffe aus dem TLS-Handshake oder vom Main-Thread (R-0643, R-0644, Vorhaben
  desktop-blocking); dieses Vorhaben ändert nur, wann ein erster Kontakt gilt.
- Kein neuer Fehlercode und keine eigene UI-Behandlung des neuen Texts (Fehlervertrag ist R-0709).
- Kein Umbau der doppelten `CredReadW`-Aufrufe in `password.rs` (R-0711); `windows_read_credential` und `os_get`
  bleiben, `get` stuft Fehler weiter zu `None` herab (`keyring_store.rs:46-57`).
- `Login.svelte` bleibt: Der Kommentar `:92-94` („require the same explicit warning the settings modal does“) stimmt,
  sobald T3 gebaut ist.
- Ein leerer Wert unter Windows gilt weiter als kein Eintrag (wie heute und wie `os_get`, `keyring_store.rs:155-160`).

## Betroffene Komponenten & Dateien

| Task | Komponente | Dateien |
|---|---|---|
| T1 | desktop-rs | `apps/desktop/src-tauri/src/tofu.rs`, `apps/desktop/src-tauri/src/session.rs` (nur Tests), `docs/developer/desktop.html`, `docs/en/developer/desktop.html`, `docs/admin/troubleshooting.html`, `docs/en/admin/troubleshooting.html`, `CHANGELOG.md` |
| T2 | desktop-rs | `apps/desktop/src-tauri/src/keyring_store.rs`, `apps/desktop/src-tauri/src/password.rs`, `CHANGELOG.md` |
| T3 | desktop-ui | `apps/desktop/ui/src/components/SettingsModal.svelte`, `apps/desktop/ui/src/components/SettingsModal.dialog.test.ts`, `docs/developer/desktop.html`, `docs/en/developer/desktop.html`, `docs/admin/troubleshooting.html`, `docs/en/admin/troubleshooting.html`, `CHANGELOG.md` |

`tofu.rs` und `keyring_store.rs` stehen auf `scripts/dev/review-risk.txt` (`:14`, `:29`): T1 und T2 bekommen
zusätzlich `security`.

## Datenmodell / API / Migrationen

Keine Migration, kein Tauri-Command neu oder geändert, keine Bridge-Typen. Der Schlüssel des Pins
(`tofu|cert|<host:port>`, `tofu.rs:189-191`) bleibt. Der Text, mit dem der Verifier einen Lese- oder Speicherfehler
ablehnt, ist Prosa ohne `ERR_*`-Code; `ERR_TOFU_PIN_MISMATCH` bleibt für einen echten Zertifikatswechsel und bleibt
der Schlüssel, an dem der Login das Zurücksetzen anbietet. Die UI nutzt den vorhandenen Key `login.resetPin.confirmMitm`
(`apps/desktop/ui/src/lib/i18n/dictionaries.ts:391`, EN `:1181`); kein neuer i18n-Key.

## Externe Integrationen

- `CredReadW` (learn.microsoft.com/en-us/windows/win32/api/wincred/nf-wincred-credreadw, gelesen 2026-10-22):
  „The following status codes can be returned: ERROR_NOT_FOUND — No credential exists with the specified
  TargetName. ERROR_NO_SUCH_LOGON_SESSION — The logon session does not exist or there is no credential set associated
  with this logon session. Network logon sessions do not have an associated credential set. ERROR_INVALID_FLAGS — A
  flag that is not valid was specified for the Flags parameter.“ Nur `ERROR_NOT_FOUND` heißt „kein Eintrag“.
- rustls `ServerCertVerifier` und der Schlüsselbund (`keyring`-Crate unter Linux/macOS) bleiben in ihrer Nutzung
  unverändert.

## Trade-offs & Alternativen

1. **Was bei einem Speicherfehler geschieht (T1).** (a) Ablehnen, ohne zu pinnen — **Empfehlung**: ein Pin, der den
   Prozess nicht überlebt, ist beim nächsten Start kein Pin. (b) Heute: im Prozess vertrauen. (c) Vertrauen und eine
   Warnung zeigen: braucht einen neuen Weg vom Verifier in die UI und lässt (b) bestehen.
2. **Text der Ablehnung (T1).** (a) Eigener englischer Text ohne Code — **Empfehlung**: ändert keinen Vertrag, der Login
   bietet dann kein Zurücksetzen an, das nicht hilft. (b) `ERR_TOFU_PIN_MISMATCH` wie heute beim Lesefehler: nennt
   einen Zertifikatswechsel, den es nicht gab. (c) Neuer Code `ERR_TOFU_PIN_STORE_…`: neuer Bestandteil des
   Fehlervertrags (R-0709) ohne eine Aktion, die die UI anbieten könnte. Der Lesefehler bekommt denselben Text wie
   der Speicherfehler (eine Variante `PinDecision::Unavailable`); das ändert die Meldung von `tofu.rs:167-171`, nicht
   die Entscheidung (abgelehnt bleibt abgelehnt).
3. **Session-Tests (T1).** Ihr Handshake läuft ohne Test-Schlüsselbund. (a) Der Testserver legt den Fingerprint seines
   Zertifikats über einen `#[cfg(test)]`-Helfer in `tofu.rs` vorab in den Prozess-Cache — **Empfehlung**: die Tests
   prüfen die Client-Wahl der Session, nicht das erste Pinnen, das `tofu.rs` selbst prüft. (b) `current_thread` mit
   `keyring_store::memory()`: ändert das Laufzeitmodell der Tests. (c) Ein prozessweiter Test-Schlüsselbund:
   Umbau aus R-0710.
4. **Rückfrage in den Einstellungen (T3).** (a) `login.resetPin.confirmMitm` wiederverwenden — **Empfehlung**: ein
   Text für denselben Schritt, kein neuer Key. (b) Eigener `settings.resetCertPin.confirm`: zwei Texte für dieselbe
   Warnung.
5. **Windows-Beweis (T2).** Ein `CredReadW`-Fehler außer `ERROR_NOT_FOUND` lässt sich auf einem CI-Runner nicht
   herbeiführen (Flags fest 0, eine Logon-Session mit Credential-Set ist da). (a) Eine `#[cfg(test)]`-Naht in
   `windows_generic_read`, thread-lokal wie `keyring_store::memory_backend` (`keyring_store.rs:109-126`), die einen
   gewählten Fehlercode statt des `CredReadW`-Ergebnisses meldet — **Empfehlung**: der Test geht durch
   `os_try_get` und ist rot, solange `os_try_get` an `windows_generic_read` vorbei liest. (b) Nur Code-Lesung: der
   Fehlerzweig bliebe unbelegt.

## Risiken & Rollback

- Ein Schlüsselbund, der lesen, aber nicht schreiben kann, ließ bisher je Prozess verbinden; danach nicht mehr, mit
  einem Text, der den Schlüsselbund nennt. Gewollt.
- Windows: Scheitert `CredReadW` dauerhaft mit einem anderen Code als `ERROR_NOT_FOUND`, lehnt der Desktop den
  ersten Kontakt ab statt neu zu pinnen, und das Löschen eines Server-Workspace (`storage.rs:299`, `launcher.rs:746`
  über `holds_identity`) meldet einen Fehler statt ohne Widerruf fortzufahren. Gewollt, wie `holds_identity` es
  beschreibt.
- GUI-E2E: Die Desktop-Suiten starten ein entsperrtes gnome-keyring (`scripts/tests/lib_e2e_stack.sh:67-89`, in
  jeder `scripts/tests/desktop_e2e_*.sh`), das Speichern gelingt; `linux-full` im Sammellauf belegt es
  (`enroll-trust-dialog.live.js`, `enroll-form.live.js` pinnen beim ersten Kontakt).
- Windows-Code läuft nur im PR-CI-Job `Desktop-Backend (cargo test, Windows)` (`.github/workflows/ci.yml:561-583`);
  clippy läuft dort nicht.
- Rollback: je Task ein Commit, `git revert`; keine Daten, keine Migration.

## Doku-Impact

T1: `docs/developer/desktop.html:242` (DE+EN): der Pin gilt erst gespeichert; Lese- oder Speicherfehler → Ablehnung
mit eigenem Text. `docs/admin/troubleshooting.html:73` (DE+EN): was bei diesem Text zu tun ist. T3:
`docs/developer/desktop.html:244` und `docs/admin/troubleshooting.html:73` (DE+EN): der Knopf fragt vorher nach.
CHANGELOG je Task. T2: nur CHANGELOG.

## Offene Fragen

Keine an Kevin. Vorschlag für die Roadmap (Nicht-Ziel 1): `forget_pin` meldet einen gescheiterten
`keyring_delete` nicht, die UI meldet „zurückgesetzt“.
