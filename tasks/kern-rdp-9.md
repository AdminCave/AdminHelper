# Eingebettetes RDP: Live-Test, OpenH264-Download, Passwort beim Neu verbinden — Task-Ledger
Status: erledigt · Branch: feature/kern-rdp-9 · Review: pro Task
Spec: docs/features/kern-rdp-9.md (Roadmap R-1258, R-1195, R-1201, R-1207, R-1196)
Heavy: linux-full — der Live-Test xrdp_live_session läuft nur in desktop_e2e_rdp_embedded (Teil gui des Sammellaufs); kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1258, R-1195: Live-Test überspringt Text und lässt Wiederverbindungen vor dem Stopp zu  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/rdp_embedded/session.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @41cd47ac0 2026-11-10T07:11:25+01:00
Review: approve (.ah-out/review/kern-rdp-9/T1.verdict.json)
Beweis: R-1258 Sammellauf 2026-11-09-0959/-1705/-2117 „expected a picture, got … Text(stats)“; R-1195 Sammellauf 2026-11-08-1600 main@d37699f5e „left: Reconnecting right: Disconnected(Closed)“
Dedup-Key: bug:desktop-e2e:scripts/tests/desktop_e2e_rdp_embedded.sh:flaky
Änderung: `next_frame` überspringt Text-Nachrichten wie Ping und Pong. Vor dem Stopp und nach dem neuen Login lässt der Test `Reconnecting` und `Connected` zu, wie schon beim Ändern der Größe; das Ende muss `Disconnected(Closed)` sein, danach kommt kein Bild mehr. Der Beweis ist der Lauf von desktop_e2e_rdp_embedded im Sammellauf; lokal kompiliert der Test nur, denn er ist ignoriert und braucht den xrdp-Container.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- rdp_embedded::session
Doku: keine (nur Test)

### T2 — R-1201, R-1207: OpenH264, aus gewinnt gegen den Download; nur auf x86_64  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/rdp_embedded/openh264.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @6ec86e701 2026-11-10T07:13:50+01:00
Review: approve (.ah-out/review/kern-rdp-9/T2.verdict.json)
Beweis: R-1201 reviewer kern-rdp-5 branch, feature/kern-rdp-5@9567a8180 openh264.rs:79,121; R-1207 kern-rdp-6 review, main@f8b5364f openh264.rs URL/FILE_NAME
Änderung: Eine prozessweite Sperre mit Generationszähler. `remove` erhöht die Generation unter der Sperre und löscht dann. `ensure` merkt sich die Generation vor dem Download, `install` schreibt nur, wenn sie unverändert ist; sonst gibt es einen Fehler und legt nichts an. Gleichzeitige `install` desselben Prozesses laufen nacheinander. Auf einer anderen Architektur als x86_64 lädt `ensure` nichts und gibt einen Fehler zurück, der die Architektur nennt. Tests: ein `remove` zwischen Download und Schreiben hinterlässt keinen Ordner; ohne `remove` schreibt `install`; die Architekturprüfung lehnt eine andere Architektur ab, ohne den Ordner anzulegen.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- rdp_embedded::openh264
Doku: → T4

### T3 — R-1196: Nach einem Anmeldefehler fragt Neu verbinden das Passwort ab  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/stores/terminals.ts, apps/desktop/ui/src/lib/stores/terminals.test.ts, apps/desktop/ui/src/lib/stores/connectFlow.ts, apps/desktop/ui/src/lib/stores/connectFlow.test.ts, apps/desktop/ui/src/components/terminal/RdpSession.svelte, apps/desktop/ui/src/components/terminal/RdpSession.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @ba979d982 2026-11-10T07:24:24+01:00
Review: approve (.ah-out/review/kern-rdp-9/T3.verdict.json)
Änderung: `reconnectRdp(key, password?)` setzt ein übergebenes Passwort für den Lauf. Neu in `connectFlow` ist `reconnectRdpTab(key)`. Endete die Sitzung mit `failed`/`auth`, zeigt es den Passwort-Dialog: Mit Merken speichert es das Passwort und startet mit dem gespeicherten, ohne Merken mit dem getippten. Abbrechen startet nichts. Ohne Anmeldefehler ruft es `reconnectRdp(key)` wie heute. Beide Knöpfe „Neu verbinden“ in `RdpSession.svelte` rufen `reconnectRdpTab`. Tests: nach `auth` fragt es, schickt das neue Passwort und startet beim Abbrechen nicht; ohne `auth` fragt es nicht; die Knöpfe rufen `reconnectRdpTab`.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/stores/terminals.test.ts src/lib/stores/connectFlow.test.ts src/components/terminal/RdpSession.test.ts
Doku: → T4

### T4 — Doku und CHANGELOG  [x]
Komponente: desktop-ui · Dateien: docs/admin/index.html, docs/en/admin/index.html, docs/developer/desktop.html, docs/en/developer/desktop.html, changelog.d/kern-rdp-9.md
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @0f1a43700 2026-11-10T07:26:05+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: DE und EN: H.264 nur unter Linux auf x86_64, „aus“ gewinnt gegen einen laufenden Download, Passwortabfrage beim Neu verbinden nach einem Anmeldefehler; CHANGELOG `### Fixed` und `### Changed`.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/stores/connectFlow.test.ts
Doku: diese Task
Task-Review: am Ende
Abhängt von: T2, T3

### T5 — R-1196: Im abgelösten Fenster verbindet Neu verbinden ohne Passwortabfrage (aus der PR-CI)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/stores/connectFlow.ts, apps/desktop/ui/src/lib/stores/connectFlow.test.ts, apps/desktop/ui/src/components/terminal/DetachedRdp.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @2d93e1bd0 2026-11-10T09:16:28+01:00
Review: approve (.ah-out/review/kern-rdp-9/T5.verdict.json)
Änderung: Das abgelöste RDP-Fenster (`DetachedRdp`, ohne `AppShell`) hat keinen `PasswordPrompt`; `reconnectRdpTab` wartete dort nach `auth` auf einen Dialog, den niemand zeigt. Eine abgelöste Sitzung verbindet daher wie vor T3 mit `reconnectRdp(key)`. Test dazu; der Mock von `$lib/stores/session` in `DetachedRdp.test.ts` liefert `sessionStore` (PR-CI #445 rot: „No "sessionStore" export is defined“).
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/stores/connectFlow.test.ts src/components/terminal/DetachedRdp.test.ts src/components/terminal/RdpSession.test.ts
Doku: keine (die Doku nennt die Abfrage im Tab; das abgelöste Fenster verhält sich wie vor dem Zug)

## Entscheidungen
- T3: `reconnectRdp(key, login?)` nimmt statt eines nackten Passworts ein `RdpLogin` (Verbindung und Passwort): Der Dialog lässt Benutzer und Domäne ändern, und nach einem Anmeldefehler ist oft der Benutzer falsch. Ohne getipptes Passwort (gemerkt) nimmt Rust das gespeicherte. `reconnectRdpTab` fragt nach jedem Ende mit Code `auth`, gleich ob `failed` oder `disconnected`.
