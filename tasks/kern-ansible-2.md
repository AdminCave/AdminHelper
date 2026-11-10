# kern-ansible-2 — Task-Ledger
Status: geplant · Branch: feature/kern-ansible-2 · Review: am Ende
Spec: docs/features/kern-ansible-2.md (Roadmap R-1213)
Heavy: none — reine Eingabeprüfung im Desktop-Backend, kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1213: Gruppennamen eines Ansible-Ziels ohne { und }  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/ansible.rs, docs/admin/ansible.html, docs/en/admin/ansible.html, changelog.d/kern-ansible-2.md
Änderung: `check_targets` lehnt einen Gruppennamen mit `{` oder `}` ab, wie Benutzer und Schlüsselpfad (Meldung englisch). Der Test `generate_inventory_rejects_host_and_group_injection` bekommt den Fall (erst rot).
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- ansible::
Doku: docs/admin/ansible.html, docs/en/admin/ansible.html, changelog.d/kern-ansible-2.md

## Entscheidungen
