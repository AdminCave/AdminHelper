# ops-9 — Agent-Einzeiler für FreeBSD und OPNsense

Roadmap: R-1598 (FEAT). R-1578 (Windows-Einzeiler) fährt nicht mit, siehe Trade-offs.

## Problem / Motivation
Linux-Hosts bekommen den Agent mit einem Befehl (`scripts/agent-install.sh`, Abschnitt Schnell-Rollout in
`docs/admin/agent-deployment.html:43`). FreeBSD und OPNsense brauchen heute einen Block aus zwölf Shell-Zeilen
(`docs/admin/agent-deployment.html:158` und `:206`): Schlüssel holen und gegen die SHA-256 prüfen, Repo-Datei
schreiben, `pkg install`, dann von Hand provisionieren und auf FreeBSD danach die Repo-Datei von Hand auf die interne
CA umstellen. `agent-install.sh` ist bash; das Basissystem von FreeBSD und OPNsense hat keins (Kevin 2026-11-18:
Provisionieren je Plattform viel einfacher).

## Ziel
`fetch -o - https://raw.githubusercontent.com/AdminCave/AdminHelper/main/scripts/agent-install-bsd.sh | sh -s --
--server https://srm.example.com --server-id <id> --ca-fp <sha256>` als root:
1. bricht ab, wenn nicht root oder nicht FreeBSD; bootstrappt `pkg`, falls nötig;
2. legt den Repo-Schlüssel ab, den das Skript selbst trägt (siehe Trade-offs), und schreibt die Repo-Datei:
   FreeBSD `/usr/local/etc/pkg/repos/adminhelper.conf`, OPNsense `AdminHelper.conf` mit `priority: 5` (der Name, unter
   dem das Plugin sie später selbst schreibt); TLS vor der Registrierung ungeprüft, die Signatur trägt die Echtheit;
3. installiert auf OPNsense (`/usr/local/sbin/opnsense-version` vorhanden) `os-adminhelper`, sonst `adminhelper-agent`;
4. mit `--server-id`: fragt den Token verdeckt auf `/dev/tty` (oder `--token` für Automatisierung) und ruft
   `adminhelper-agent provision --url … --token-stdin --server-id … [--ca-fp …]`;
5. nach erfolgreicher Registrierung TLS auf die interne CA: FreeBSD schreibt die Repo-Datei mit
   `SSL_CA_CERT_FILE: "/usr/local/etc/adminhelper/identity/ca.crt"` neu, OPNsense lässt das Plugin sie schreiben
   (`configctl firmware reload`, `apps/agent/opnsense/src/opnsense/scripts/firmware/repos/AdminHelper.sh:88`);
   dann `pkg update -r <repo>` als Probe. Ist der Host schon enrollt (`identity/ca.crt` vorhanden), schreibt schon
   Schritt 2 die geprüfte Form.
6. Ohne `--server-id`: nur Paket einrichten oder aktualisieren (wie unter Linux).

Optionen für eigene Repos und Tests: `--pubkey <datei>` (anderer Repo-Schlüssel, wie `--gpg-fp` unter Linux);
`AH_REPO_BASE` und Pfad-Variablen nur für die Tests, wie in `agent-install.sh`.

## Nicht-Ziele
- Kein Einzeiler im Provisionierungs-Tab des Desktops für FreeBSD/OPNsense (eigene Zeile, falls gewünscht).
- Keine Prüfung des TLS-Erstkontakts von `pkg` gegen `--ca-fp` vor der Registrierung: `--ca-fp` sichert die
  Provisionierung, `pkg` vertraut bis zur Registrierung nur der Signatur (heutiger Stand der Doku).
- Windows (R-1578), Desinstallation, i386/arm64.

## Betroffene Komponenten & Dateien
- neu `scripts/agent-install-bsd.sh` (POSIX sh, SPDX), neu `scripts/tests/agent_install_bsd_test.sh` (hermetisch unter
  `dash` mit Stubs für `pkg`, `fetch`, `adminhelper-agent`, `configctl`), Eintrag in `scripts/tests/run.sh`
  (`AH_SCRIPT_TESTS_DEFAULT`).
- `scripts/tests/box_freebsdbox.sh` und `scripts/tests/box_opnsensebox.sh` (Phase `pkg`, ab `:140` bzw. `:277`): das
  Skript gegen das signierte lokale Repo der Box (`AH_REPO_BASE=file://…`, `--pubkey` des Wegwerf-Schlüssels), ohne
  `--server-id`; danach mit vorhandener `identity/ca.crt` erneut: die Repo-Datei in geprüfter Form nimmt das echte
  `pkg update` an.
- `docs/admin/agent-deployment.html` + EN (Abschnitte FreeBSD und OPNsense: Einzeiler zuerst, Handweg bleibt),
  `changelog.d/ops-9.md`.

## Datenmodell / API / Migrationen
Keine. Kein neuer Agent-Befehl; `provision --token-stdin` und `--ca-fp` hat der Agent, den das Repo ausliefert.

## Externe Integrationen
`pkg.conf(5)`/`pkg-repository(5)`: Repo-Datei mit `signature_type: "pubkey"`, `ENV`/`env` je Repo
(`SSL_CA_CERT_FILE`, `SSL_NO_VERIFY_PEER`); die Form ist die der heutigen Doku, die die Box-Tests schon mit echtem
`pkg` fahren. `fetch(1)` statt curl.

## Trade-offs & Alternativen
- **Schlüssel im Skript statt Download + SHA-256** (Empfehlung): Das Skript kommt aus demselben Repo wie
  `apps/agent/freebsd/adminhelper-pkg.pub`; die Vertrauenswurzel ist die Quelle des Skripts, wie der gepinnte
  Fingerprint in `agent-install.sh`. Ein zweiter Download (GitHub-Tag, Repo-Plane führt den Schlüssel nicht) brächte
  nichts außer einem Netzpfad mehr. Der Test hält Skript-Schlüssel, Datei und den `PUBSHA` der Doku gleich.
  Alternative: Download von `raw.githubusercontent.com/…/v<version>/…` und Vergleich gegen eine im Skript gepinnte
  SHA-256 — gleiche Vertrauenswurzel, mehr Fehlerquellen.
- **R-1578 nicht in diesem Zug:** seine Notiz sagt „nach kern-windows-1 und R-1575“; R-1575 fährt in ci-15, und die
  Bootstrap-Frage (minisign-Prüfung unter Windows) ist offen. R-1578 wandert in `tasks/ops-10.md`.

## Risiken & Rollback
Neues Skript, nichts Bestehendes ändert sein Verhalten; Rollback = Revert. Risiko: ein Fehler in der Repo-Datei
schaltet das Repo still ab (pkg meldet nur eine Warnung) — der Installer prüft nach `pkg update` mit `pkg rquery`, ob
das Paket sichtbar ist, und bricht sonst ab.

## Doku-Impact
`docs/admin/agent-deployment.html` DE+EN (FreeBSD, OPNsense), `changelog.d/ops-9.md`. Die Abschnitte überlappen mit
offenen Branches (ops-8, kern-windows-1): die Doku-Task baut erst nach deren Merge auf frischem `origin/main`.

## Offene Fragen
Keine aus Kevins Bereich.
