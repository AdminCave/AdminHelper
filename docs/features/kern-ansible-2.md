# kern-ansible-2 — Ansible-Ziele: Gruppennamen wie die übrigen Inventarwerte prüfen

Roadmap: R-1213. Verschoben in kern-ansible-3: R-1214 (Frage an Kevin, siehe unten).

## Problem / Motivation

- **R-1213:** `check_targets` (`apps/desktop/src-tauri/src/ansible.rs:32`) lehnt `{` und `}` in Benutzer und
  Schlüsselpfad eines Ziels ab, weil Ansible Inventarwerte als Vorlage auswertet. Die Gruppennamen (die Tags der
  Server) prüft es nur auf Steuerzeichen und `[`/`]`.

## Ziel & Nicht-Ziele

- Ziel: Ein Tag mit `{` oder `}` startet keinen Lauf; die Meldung nennt den Grund, wie bei Benutzer und
  Schlüsselpfad.
- Nicht-Ziel: Tags am Server-Eintrag einschränken (sie dienen auch der Suche); nur der Ansible-Lauf lehnt ab.

## Betroffene Komponenten & Dateien

- `apps/desktop/src-tauri/src/ansible.rs` (`check_targets`, Test `generate_inventory_rejects_host_and_group_injection`).
- Doku `docs/admin/ansible.html`, `docs/en/admin/ansible.html` (Abschnitt Gruppen); `changelog.d/kern-ansible-2.md`.

## Datenmodell / API / Migrationen

Keine. Tauri-Command und Inventarformat bleiben.

## Externe Integrationen

Ansible-Inventar (JSON über das `yaml`-Plugin): unverändert.

## Trade-offs & Alternativen

- Ablehnen statt maskieren: dieselbe Regel wie für Benutzer und Schlüsselpfad; ein Tag mit geschweiften Klammern ist
  als Ansible-Gruppe ohnehin unüblich.

## Risiken & Rollback

Ein bestehender Tag mit `{`/`}` lässt den Lauf über ihn nicht mehr starten. Rollback: Revert des Task-Commits.

## Doku-Impact

`docs/admin/ansible.html` und die EN-Fassung: der Satz zu den Gruppen nennt die abgelehnten Zeichen.

## Offene Fragen

- **R-1214 (Kevin, kern-ansible-3):** Ein Sprung-Host bei einem Lauf mit `--ask-pass`: (a) hinnehmen, (b) für einen
  in der Verbindung gesetzten Sprung-Host ein eigenes Proxy-Kommando ohne Passwort-Anmeldung bauen (ein Sprung-Host
  aus `~/.ssh/config` bleibt außen vor), (c) einen solchen Lauf ablehnen. Empfehlung: (b), weil Läufe über Sprung-Hosts
  weiter gehen; Einzelheiten in der Roadmap-Notiz.
