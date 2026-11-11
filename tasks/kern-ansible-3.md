# kern-ansible-3 — Task-Ledger
Status: geplant · Branch: feature/kern-ansible-3 · Review: pro Task
Spec: docs/features/kern-ansible-3.md (Roadmap R-1214)
Heavy: none — Inventar-Erzeugung im Desktop-Backend, kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1214: Sprung-Host der Verbindung als ProxyCommand-Kette bei --ask-pass  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/ansible.rs
Änderung: In einem Lauf mit `--ask-pass` ersetzt `host_vars` das `-o ProxyJump=<hops>` aus `option_switches` durch `-o ProxyCommand=ssh -o PasswordAuthentication=no -o KbdInteractiveAuthentication=no [-o ProxyCommand=<inneres Bein, %% verdoppelt>] -W [%h]:%p [-l u] [-p p] <hop>`, verschachtelt je Hop der Kette, jeder Wert shell-gequotet. Ohne `--ask-pass` bleibt `ProxyJump`. Tests: Kette mit einem und drei Hops samt IPv6 im letzten Hop, Lauf ohne `--ask-pass` unverändert; unter Unix prüft ein Test mit dem echten `ssh -G -F /dev/null`, dass ssh `proxycommand` und kein `proxyjump` sieht.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- ansible::
Doku: → T3

### T2 — R-1214: ProxyJump aus der SSH-Konfiguration bei --ask-pass  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/ansible.rs
Abhängt von: T1
Änderung: Hat ein Ziel in einem Lauf mit `--ask-pass` keinen eigenen Sprung-Host, löst `generate_inventory` `ProxyJump` über `ssh -G [-l user] [-p port] <host>` auf. Ein gesetzter Wert (nicht `none`) wird wie in T1 zur Kette. Bricht `ssh -G` ab oder lehnt `JUMP_RE` einen Hop ab, startet der Lauf nicht, die Meldung ist englisch und nennt das Ziel. Den Resolver kann der Test einsetzen. Tests: Resolver liefert Kette → ProxyCommand; `none` und leer → unverändert; Fehler → Validation-Fehler; unter Unix das echte `ssh -G -F <Temp-Konfig>` mit `ProxyJump`.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- ansible::
Doku: → T3

### T3 — R-1214: Doku DE+EN und CHANGELOG  [ ]
Komponente: scripts · Dateien: docs/admin/ansible.html, docs/en/admin/ansible.html, changelog.d/kern-ansible-3.md
Änderung: Inventar-Abschnitt und Kasten SSH-Erreichbarkeit nennen, dass das Sprung-Bein in Läufen mit `--ask-pass` als eigenes `ProxyCommand` ohne Passwort-Anmeldung läuft, auch für `ProxyJump` aus `~/.ssh/config`. Ein eigenes `ProxyCommand` aus der Konfiguration bleibt, wie es ist. CHANGELOG neutral unter Security.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/admin/ansible.html, docs/en/admin/ansible.html, changelog.d/kern-ansible-3.md
Task-Review: am Ende

## Entscheidungen
