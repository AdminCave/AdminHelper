# Agent-Einzeiler für FreeBSD und OPNsense — Task-Ledger
Status: bereit · Branch: feature/ops-9 · Review: am Ende
Spec: docs/features/ops-9.md (Roadmap R-1598)
Heavy: scenario --box freebsd,opnsense — neues Installer-Skript; `scripts/tests/freebsd_box.sh` und `scripts/tests/opnsense_box.sh` fahren es mit echtem sh und pkg auf den Vorlagen base-freebsd und base-opnsense (Kevin 2026-11-18: grüner VM-Lauf ist Bedingung für den Selbst-Merge).
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1598: scripts/agent-install-bsd.sh mit hermetischem Test  [x]
Komponente: scripts · Dateien: scripts/agent-install-bsd.sh, scripts/tests/agent_install_bsd_test.sh, scripts/tests/run.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @24fc7e67d 2026-11-18T17:28:48+01:00
Review: am Ende (Branch-Review)
Änderung: Neues POSIX-sh-Skript nach Spec (Schlüssel im Skript, `--pubkey`, Repo-Datei je Plattform, `os-adminhelper` oder `adminhelper-agent`, Token verdeckt über `/dev/tty` oder `--token`, `provision --token-stdin`, danach TLS auf die interne CA; Abbruch, wenn das Paket nach `pkg update` nicht sichtbar ist). SPDX in beiden neuen Dateien. Der Test läuft unter `dash` mit Stubs und prüft: Repo-Datei vor und nach der Registrierung (FreeBSD, OPNsense über `configctl`), Paketwahl, Token nie in argv, ohne `--server-id` keine Provisionierung, Abbruch ohne root, Skript-Schlüssel gleich `apps/agent/freebsd/adminhelper-pkg.pub` und gleich `PUBSHA` der Doku. Eintrag in `AH_SCRIPT_TESTS_DEFAULT`.
Verify: bash scripts/dev/verify.sh scripts --strict -- agent_install_bsd_test
Doku: → T3

### T2 — R-1598: Box-Tests fahren den Installer auf echtem FreeBSD und OPNsense  [x]
Komponente: scripts · Dateien: scripts/tests/box_freebsdbox.sh, scripts/tests/box_opnsensebox.sh, scripts/agent-install-bsd.sh, scripts/tests/agent_install_bsd_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @e93012cf3 2026-11-18T17:36:00+01:00
Review: am Ende (Branch-Review)
Änderung: In Phase `pkg` installiert der Installer (ohne `--server-id`, `AH_REPO_BASE=file://` auf das signierte Wegwerf-Repo, `--pubkey` dessen Schlüssel) das Paket bzw. das Plugin; ein zweiter Lauf mit einer vorhandenen `identity/ca.crt` schreibt die geprüfte Repo-Datei, die das echte `pkg update` annimmt. Die bestehenden Prüfungen bleiben.
Verify: bash scripts/dev/verify.sh scripts --strict -- box_scripts_guard_test
Abhängt von: T1
Doku: keine (Testharness)

### T3 — R-1598: Doku FreeBSD und OPNsense, Changelog  [x]
Komponente: scripts · Dateien: docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, changelog.d/ops-9.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @40c60d95a 2026-11-19T08:00:15+01:00
Review: am Ende (Branch-Review)
Änderung: Abschnitte FreeBSD und OPNsense nennen den Einzeiler zuerst (was er tut, `--pubkey`, ohne `--server-id` nur Paket), der Handweg bleibt darunter; Umstellung auf die interne CA nur noch für den Handweg. Erst nach dem Merge von ops-8 und kern-windows-1 auf frischem `origin/main` (gleiche Datei).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, changelog.d/ops-9.md
Task-Review: am Ende
Abhängt von: T1

### T4 — R-1598: Abschlussprüfung: TOFU ohne --ca-fp, Doku-Nits  [x]
Komponente: scripts · Dateien: scripts/agent-install-bsd.sh, scripts/tests/agent_install_bsd_test.sh, docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, README.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @590f14de8 2026-11-19T08:21:42+01:00
Review: am Ende (Branch-Review)
Änderung: Ohne `--ca-fp` ruft das Skript `provision` mit `--insecure` (TOFU wie agent-install.sh; sonst prüft der Agent gegen die System-Roots und scheitert an der internen CA), Test prüft das; fehlendes `</p>`, `--repo-port` auf OPNsense nur bis zur Registrierung, README-Verweis auf den BSD-Einzeiler.
Verify: bash scripts/dev/verify.sh scripts --strict -- agent_install_bsd_test
Doku: docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, README.md
Abhängt von: T3

## Entscheidungen
- 2026-11-18 Gate: R-1578 fährt nicht mit (Notiz: nach kern-windows-1 und R-1575; R-1575 in ci-15) → `tasks/ops-10.md`.
- 2026-11-18 Gate: Repo-Schlüssel steht im Skript statt Download + gepinnter SHA-256 (gleiche Vertrauenswurzel, ein Netzpfad weniger); der Test hält Skript, Schlüsseldatei und Doku-`PUBSHA` gleich.
- 2026-11-18 Ops-9: Kevin: OPNsense-Lauf mit fremdem rotem Probe-Test (R-1610) gilt als grüner scenario-Lauf für den Selbst-Merge.
- 2026-11-19 T1: Das Skript ruft das Repo-Skript des Plugins direkt statt `configctl firmware reload` (gleiche Wirkung, ohne configd-Abhängigkeit im Installer); Branch-Review-Nit.
