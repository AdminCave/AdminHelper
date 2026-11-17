<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-monitoring-39: HAProxy fehlender Reload, Platz in moodledata

Roadmap R-1502, R-1504; beide Nicht-Ziele aus kern-monitoring-28. R-1503 (vHosts im Container) fährt nicht mit,
sondern geht mit einer Frage an Kevin in den Zug kern-monitoring-42.

## Problem / Motivation

- **R-1502:** Das Modul `haproxy` liest die Restlaufzeit der Zertifikatsdateien aus `bind … crt`. Nach einer
  Erneuerung ohne Reload liefert HAProxy aber weiter das alte Zertifikat aus. Ein Handshake hilft hier nicht, denn
  ohne SNI liefert HAProxy nur sein Standard-Zertifikat. Der Stats-Socket kennt dagegen jedes geladene Zertifikat:
  `show ssl cert <file>` zeigt das im Speicher geladene Zertifikat.
- **R-1504:** Läuft das moodledata-Verzeichnis voll (Platz oder Inodes), fallen Uploads und Caches aus. Das
  Verzeichnis liegt oft auf einem eigenen Dateisystem, das der Host-Check nicht kennt.

## Ziel & Nicht-Ziele

**Ziel:**

- `haproxy_certs` fragt zusätzlich den Stats-Socket:
  - `show ssl cert` liefert die Liste der geladenen Dateien.
  - Für jede Zertifikatsdatei aus `bind … crt`, die in der Liste steht, liest `show ssl cert <file>` deren
    `notAfter`.
  - `reload_missing` zählt die Dateien, deren erstes Zertifikat länger läuft als das geladene (wie bei
    `web_vhost_cert`).
  - Das Feld fehlt, wenn der Agent keinen Socket findet oder der Socket die Frage ablehnt. Laut Quelltext von
    HAProxy 3.2.0 (`src/ssl_ckch.c`, `cli_parse_show_cert`) verlangt die Frage die Stufe `operator`.
  - Regel: `reload_missing > 0` gibt warning.
- Neue App-Ansicht `moodle_data` (vhost):
  - Sie liest das `$CFG->dataroot` aus der `config.php` des Dokumentverzeichnisses. Das ist dieselbe Regel wie bei
    `moodle_checks`, sie führt aber keinen Code aus.
  - Danach fragt sie `statfs` am dataroot, wie der Sensor `fs`. Felder: `used_pct`, `free_bytes`,
    `inodes_used_pct`.
  - Neuer Check `data` im Modul `moodle_native`, alle 15 Minuten. Regeln wie beim Datenträger-Check von
    VictoriaMetrics: ab 80 % warning, ab 90 % critical, Inodes ab 90 % warning.

**Nicht-Ziele:**

- moodledata der Container-Images (Pfade je Image verschieden);
- `crt-list` und `crt-store`, wie bisher;
- Zertifikate, die per `set ssl cert` geändert und nicht committet wurden (Einträge mit `*`). Sie werden
  übersprungen.

## Betroffene Komponenten & Dateien

**Agent:**

- `apps/agent/internal/probe/app_haproxy.go`: `haproxyCerts`, neuer Parser für `show ssl cert`.
- `app_haproxy_certs_linux_test.go`
- `app_moodle.go`, `app_moodle_unix.go`, `app_moodle_windows.go`: Ansicht `moodle_data`. Unter Windows meldet
  sie `unsupported`, wie `moodle_checks`.
- `app_moodle_linux_test.go`
- `sensor_app.go`

**Monitoring:**

- `app/catalog/modules/haproxy.py`: Feld und Regel, Version +1.
- `app/catalog/modules/moodle_native.py`: Check `data`, Version 2.
- Tests in `tests/test_catalog_*.py`.

**Doku:** `docs/admin/monitoring.html` DE und EN (Zeilen `haproxy` und Moodle), `docs/developer/agent.html` DE und EN
(Ansichten), `changelog.d/kern-monitoring-39.md`.

## Datenmodell / API / Migrationen

Keine Migration. Es kommen nur neue Felder in den App-Werten hinzu (Zahlen). Pfade und Dateinamen bleiben auf dem
Host.

## Externe Integrationen

HAProxy Management Guide 3.2, §9.3 `show ssl cert`. Ausgabe: `Filename:`, `Status:`, `Serial:`, `notBefore:`,
`notAfter:` (`Dec 12 21:20:24 2019 GMT`) und weitere. Ohne Argument kommt die Liste der Dateien, nicht committete
mit `*` davor. Die Stufe `operator` stammt aus dem Quelltext v3.2.0. Welche Stufe ein Socket standardmäßig hat, ist
nicht verifiziert. Deshalb gilt eine Ablehnung als „kein Feld“ und nicht als Fehler.

## Trade-offs & Alternativen

- Seriennummer statt `notAfter` vergleichen: Das würde jede Abweichung finden, auch ein zurückgerolltes Zertifikat.
  Das Konzept verlangt aber „Datei neu, ausgeliefert alt“. `notAfter` folgt `web_vhost_cert`. Empfehlung:
  `notAfter`.
- `dump ssl cert`: Die Stufe `admin` ist nötig, und die Ausgabe enthält den privaten Schlüssel. Ausgeschlossen.

## Risiken & Rollback

- Ein Name in der Liste, den HAProxy anders schreibt als der Agent, etwa wegen `crt-base`: Die Datei wird dann nicht
  verglichen. Es kommt kein falscher Alarm, das Feld zählt nur Treffer.
- Rollback: die Commits zurücknehmen; die Modulversionen fallen zurück.

## Doku-Impact

Die Modultabelle (haproxy: der Satz „prüft nicht, ob neu geladen wurde“ fällt; Moodle: der Check `data`) und die
Ansichten im Entwicklerhandbuch, jeweils DE und EN, dazu der CHANGELOG.

## Offene Fragen

keine für diesen Zug. Für R-1503 im Zug kern-monitoring-42: Zwei Wege stehen zur Wahl. Entweder `docker exec`
(`nginx -T` bzw. `apachectl -S` im Container), oder das Archiv der Konfiguration per Docker-API-GET mit eigenem
Parser. Empfehlung: GET, denn das Konzept sagt beim Container „kein exec“.
