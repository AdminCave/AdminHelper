# Eingebettetes RDP: Live-Test, OpenH264-Download, Passwort beim Neu verbinden — Task-Ledger
Status: aktiv · Branch: feature/kern-rdp-9 · Review: pro Task
Spec: docs/features/kern-rdp-9.md (Roadmap R-1258, R-1195, R-1201, R-1207, R-1196)
Heavy: linux-full — der Live-Test xrdp_live_session läuft nur in desktop_e2e_rdp_embedded (Teil gui des Sammellaufs); kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1258, R-1195: Live-Test überspringt Text und lässt Wiederverbindungen vor dem Stopp zu  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/rdp_embedded/session.rs
Beweis: R-1258 Sammellauf 2026-11-09-0959/-1705/-2117 „expected a picture, got … Text(stats)“; R-1195 Sammellauf 2026-11-08-1600 main@d37699f5e „left: Reconnecting right: Disconnected(Closed)“
Dedup-Key: bug:desktop-e2e:scripts/tests/desktop_e2e_rdp_embedded.sh:flaky
Änderung: `next_frame` überspringt Text-Nachrichten wie Ping und Pong. Vor dem Stopp und nach dem neuen Login lässt der Test `Reconnecting` und `Connected` zu, wie schon beim Ändern der Größe; das Ende muss `Disconnected(Closed)` sein, danach kommt kein Bild mehr. Der Beweis ist der Lauf von desktop_e2e_rdp_embedded im Sammellauf; lokal kompiliert der Test nur, denn er ist ignoriert und braucht den xrdp-Container.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- rdp_embedded::session
Doku: keine (nur Test)

### T2 — R-1201, R-1207: OpenH264, aus gewinnt gegen den Download; nur auf x86_64  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/rdp_embedded/openh264.rs
Beweis: R-1201 reviewer kern-rdp-5 branch, feature/kern-rdp-5@9567a8180 openh264.rs:79,121; R-1207 kern-rdp-6 review, main@f8b5364f openh264.rs URL/FILE_NAME
Änderung: Eine prozessweite Sperre mit Generationszähler. `remove` erhöht die Generation unter der Sperre und löscht dann. `ensure` merkt sich die Generation vor dem Download, `install` schreibt nur, wenn sie unverändert ist; sonst gibt es einen Fehler und legt nichts an. Gleichzeitige `install` desselben Prozesses laufen nacheinander. Auf einer anderen Architektur als x86_64 lädt `ensure` nichts und gibt einen Fehler zurück, der die Architektur nennt. Tests: ein `remove` zwischen Download und Schreiben hinterlässt keinen Ordner; ohne `remove` schreibt `install`; die Architekturprüfung lehnt eine andere Architektur ab, ohne den Ordner anzulegen.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- rdp_embedded::openh264
Doku: → T4

### T3 — R-1196: Nach einem Anmeldefehler fragt Neu verbinden das Passwort ab  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/stores/terminals.ts, apps/desktop/ui/src/lib/stores/terminals.test.ts, apps/desktop/ui/src/lib/stores/connectFlow.ts, apps/desktop/ui/src/lib/stores/connectFlow.test.ts, apps/desktop/ui/src/components/terminal/RdpSession.svelte, apps/desktop/ui/src/components/terminal/RdpSession.test.ts
Änderung: `reconnectRdp(key, password?)` setzt ein übergebenes Passwort für den Lauf. Neu in `connectFlow` ist `reconnectRdpTab(key)`. Endete die Sitzung mit `failed`/`auth`, zeigt es den Passwort-Dialog: Mit Merken speichert es das Passwort und startet mit dem gespeicherten, ohne Merken mit dem getippten. Abbrechen startet nichts. Ohne Anmeldefehler ruft es `reconnectRdp(key)` wie heute. Beide Knöpfe „Neu verbinden“ in `RdpSession.svelte` rufen `reconnectRdpTab`. Tests: nach `auth` fragt es, schickt das neue Passwort und startet beim Abbrechen nicht; ohne `auth` fragt es nicht; die Knöpfe rufen `reconnectRdpTab`.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/stores/terminals.test.ts src/lib/stores/connectFlow.test.ts src/components/terminal/RdpSession.test.ts
Doku: → T4

### T4 — Doku und CHANGELOG  [ ]
Komponente: desktop-ui · Dateien: docs/admin/index.html, docs/en/admin/index.html, docs/developer/desktop.html, docs/en/developer/desktop.html, changelog.d/kern-rdp-9.md
Änderung: DE und EN: H.264 nur unter Linux auf x86_64, „aus“ gewinnt gegen einen laufenden Download, Passwortabfrage beim Neu verbinden nach einem Anmeldefehler; CHANGELOG `### Fixed` und `### Changed`.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/stores/connectFlow.test.ts
Doku: diese Task
Task-Review: am Ende
Abhängt von: T2, T3

## Entscheidungen
