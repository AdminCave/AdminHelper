# ops-15 — Nachlese ops-14 und Folgearbeit an den Install-Skripten

Roadmap: R-1684 (Nachlese ops-14, Einzelheiten privat), R-0592 (Install-Skripte, Folgearbeit aus R-0530/R-0538/R-0531).

## Problem / Motivation
**R-1684** sammelt die Nits der Prüfer aus ops-14 (R-0460, Digest-Pins aus dem signierten Bundle):
- `scripts/release/image-pins.sh:51` gibt einen Digest, der nicht die Form `sha256:<64 hex>` hat, vollständig aus.
- `.github/workflows/release.yml`: Der Pin-Schritt (`Pin the signed tag images by digest`, Zeile 423) läuft im Job
  `release` mit dessen Rechten und Umgebung.
- `scripts/update.sh:1090-1092`: `image_pins` läuft ein zweites Mal nach dem Tausch der Laufzeit-Dateien und der
  `.env`-Migration; scheitert es dort, meldet `die` „aborted, nothing changed“, obwohl sich schon etwas geändert hat.
  Praktisch unerreichbar (`fetch_bundle` prüft dieselbe Datei, Zeile 524), die Meldung stimmt aber nicht.
- `scripts/install.sh:197` lässt die Datei `IMAGES` im Installationsverzeichnis liegen, `update.sh` tauscht sie mit
  den Laufzeit-Dateien hinein (`MANIFEST_PATHS`, Zeile 907). Kein Skript liest die Kopie.
- `scripts/tests/upgrade_path_test.sh:322` entscheidet, ob ein Digest-Pin erwartet wird, an genau dieser Kopie, die das
  geprüfte `update.sh` selbst ablegt.

**R-0592**:
- (a) Die Arbeitskopien `.env.ah-*` (`install.sh:641`, `update.sh:392`, `:891`, `:1057`) bleiben liegen, wenn das
  Skript zwischen Anlegen und `mv` endet; die beiden Rollbacks schreiben in den festen Namen `.env.ah-new`.
- (b) Der Kopfkommentar von `scripts/uninstall.sh` (Zeile 11) und die Beispiel-Kommentare in
  `docs/admin/installation.html:256`/`:260` (EN `:204`/`:208`) nennen `./repo` bei den Host-Daten nicht.
- (c) `update_test.sh` war bei parallelen Läufen einmal rot (nicht verifiziert).
- (d) Test 40 „append“ (`update_test.sh:1408-1417`) prüft Exit, Fehlermeldung und Rollback-Text in einer Bedingung;
  `bad` nennt nur den Exit.

## Ziel & Nicht-Ziele
- `image-pins.sh` nennt einen kaputten Digest nur nach Länge, nicht wörtlich.
- Der Pin-Schritt läuft in einem eigenen Job mit minimalen Rechten (`permissions: contents: read`); `IMAGES`
  geht als Artefakt an den Job `release`, der es ins Bundle legt.
- `update.sh` liest die Pins einmal, direkt nach der Übergabe an das `update.sh` des Ziels und vor jeder Änderung.
- `IMAGES` bleibt nicht im Installationsverzeichnis (install entfernt es wie `VERSION`, update tauscht es nicht ein).
- `upgrade_path_test` fragt das Bundle von `PREV` (Asset-Inhalt), ob es `IMAGES` trägt.
- Arbeitskopien der `.env` tragen zufällige Namen (`mktemp`) und gehen auch bei Abbruch weg (EXIT-Trap).
- `./repo` in Kopfkommentar und Doku-Beispielen; Test 40 „append“ meldet jede Bedingung einzeln.
- **Nicht-Ziele:** keine Änderung an der Prüfung von `IMAGES`, an cosign oder an der minisign-Signatur; kein
  Umbau der Rollbacks über die Namen der Arbeitskopien hinaus.

## Betroffene Komponenten & Dateien
`scripts/release/image-pins.sh`, `scripts/tests/image_pins_test.sh`, `.github/workflows/release.yml`,
`apps/server/tests/test_release_images.py`, `scripts/install.sh`, `scripts/update.sh`, `scripts/uninstall.sh`,
`scripts/tests/install_test.sh`, `scripts/tests/update_test.sh`, `scripts/tests/upgrade_path_test.sh`,
`docs/admin/installation.html` + `docs/en/admin/installation.html`, `docs/developer/cicd.html` +
`docs/en/developer/cicd.html`, `changelog.d/ops-15.md`.

## Datenmodell / API / Migrationen
Keine. Das Bundle-Format bleibt; nur liegt `IMAGES` danach nicht mehr im Installationsverzeichnis.

## Externe Integrationen
GitHub Actions: Artefakt-Übergabe zwischen Jobs mit `actions/upload-artifact`/`actions/download-artifact`
(gepinnt wie die übrigen Actions in `release.yml`); vor dem Bau in der offiziellen Doku nachlesen.

## Trade-offs & Alternativen
- **Eigener Pin-Job** statt Schritt im Job `release`: der Pin-Schritt bekommt nur die Rechte, die er braucht. Kosten: ein Job mehr, eine Artefakt-Übergabe. Der Pin-Job kann parallel zu den Bau-Jobs laufen und
  auf `docker.yml` warten.
- **Pins früh lesen** statt die Meldung zu ändern: dann gibt es den späten Fehlerfall nicht mehr.
- **IMAGES entfernen** statt die Doku zu lassen („liest kein Skript“): eine Datei, die nichts bewirkt, verleitet zum
  Edit.

## Risiken & Rollback
- `release.yml` ist erst mit dem nächsten Tag real bewiesen; bis dahin der Struktur-Test in `test_release_images.py`.
- `update.sh`/`install.sh`: `update_test`, `install_test`, `upgrade_path_test` (Sammellauf, `Heavy: linux-full`).
- Rollback: Revert des PR.

## Doku-Impact
`installation.html` DE+EN (Satz zur Kopie von `IMAGES`; `./repo` in den Beispielen), `cicd.html` DE+EN (eigener Pin-Job), `changelog.d/ops-15.md`.

## Offene Fragen
Keine. Kevin 2026-11-23: beide Zeilen angenommen in ops-15.
