<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# UniFi OS Server lokal — Spec

Roadmap R-1244 (lokaler Teil). Site Manager zentral, der Reiter „Geräte“ und die Geräteliste kommen mit R-1518
(arch, Kevin 2026-11-15).

## Problem / Motivation
Ein UniFi OS Server (UOS, Unit `uosserver`, Podman) betreibt die Network-Anwendung, die Switches, APs und Gateways
verwaltet. Das Monitoring sieht heute nur Dienst und Ports, aber nicht, ob die Geräte selbst laufen. Die lokale
Integration API (Network ab 10.1.84) gibt Zustände her. Ihr Key hat aber keine Scopes und kann handeln: Neustart,
PoE-Power-Cycle, `DELETE /devices/{id}` (Werksreset eines Geräts, das online ist), WLAN und Firewall ändern.

## Ziel & Nicht-Ziele
Ziel:
- Ansicht `unifi_network` im Agent. Sie fragt die Integration API des eigenen Hosts über Loopback ab, mit einem
  eigenen HTTP-Client: nur `GET`, Pfad-Freigabeliste, keine Redirects, Key nur an den Port, den `uosserver` hält
  (`secretGuard`).
- Sie sendet nur Zahlen: `sites`, `devices`, `offline`, `offline_root`, `gateways_offline`, `updating`,
  `firmware_updatable`, `pending`, `clients`.
- Modul `unifi-os-server`: erkannt an der Unit `uosserver`. Checks: Dienst, Zertifikat des Web-Ports und die
  Ansicht alle 5 min. Ein Gateway offline ist `critical`, eine Ursache offline (`offline_root`) ist `warning`. Der
  Key liegt im lokalen Credential-Speicher des Agenten (`header:X-API-KEY`, Slot `default`).
- Ein Test auf einer frisch installierten UOS-VM im Pool `adminhelper-ci`, nicht geklont (Kevin 2026-11-15). Er
  prüft Port, Header und was ein View-Only-Key darf.

Nicht-Ziele:
- Geräteliste mit Namen in der Karte (R-1518).
- Site Manager (R-1518).
- PoE-Zustand und Port-Speed: Sie stehen nur in den Details je Gerät, die Ansicht bräuchte dafür mehr als 20
  Anfragen je Lauf.
- Statistik je Gerät.
- Die Alarmverzögerung für UPDATING/ADOPTING (30 min): `updating` wird gezählt, löst aber keine Regel aus.
- UniFi-OS-Konsolen (UDM, UCG, Cloud Key; keine LAN-Sonde, Konzept §10 Nr. 4).
- Der alte Network Server (Konzept §10 Nr. 18).

## Betroffene Komponenten & Dateien
- Agent:
  - neu `apps/agent/internal/probe/app_unifi.go` (Client, Ansicht) und `app_unifi_test.go`
  - `sensor_app.go` (Eintrag in `appViews`, `uses: header:X-API-KEY`)
- Monitoring:
  - `apps/monitoring/app/catalog/sensors.py` (Felder und Ziel der Ansicht, Liste der Ansichten)
  - neu `apps/monitoring/app/catalog/modules/unifi_os_server.py`
  - neu `apps/monitoring/tests/test_catalog_unifi.py`
  - `tests/test_catalog_sensors.py`
- Doku: `docs/admin/monitoring.html`, `docs/developer/agent.html` (DE+EN), `changelog.d/kern-monitoring-13.md`.

## Datenmodell / API / Migrationen
Keine Migration und kein Vertrag Server ↔ Web ↔ Desktop: Die Ansicht liefert nur Zahlenfelder, wie die bestehenden
Ansichten. Ein älterer Agent meldet den Check `invalid`, bis er aktualisiert ist.

## Externe Integrationen
UniFi Network Integration API v11.0.97 (OpenAPI von developer.ui.com):
- Basis `https://<host>/proxy/network/integration`
- `GET /v1/info`, `/v1/sites`, `/v1/sites/{siteId}/devices` (offset/limit ≤ 200, `totalCount`),
  `/v1/sites/{siteId}/devices/{deviceId}` (`uplink.deviceId`), `/v1/pending-devices`, `/v1/sites/{siteId}/clients`
- Device-`state` ONLINE … ISOLATED; `features` mit `gateway`; `firmwareUpdatable`.

Abfrage je Lauf (sequenziell, höchstens 20 Anfragen):
1. `info` als Lebend- und Zugangsprobe.
2. Sites.
3. Geräte je Site (`limit=200`, Seiten bis `totalCount`).
4. Details nur der Geräte, die offline sind, höchstens 8 (für `uplink.deviceId`: hängt das Gerät an einem Gerät,
   das selbst offline ist, zählt es nicht zu `offline_root`).
5. Pending-Geräte und Clients je mit `limit=1` (nur `totalCount`).

Nicht verifiziert bis zum Lab-Test (T3): Header-Name `X-API-KEY` (die Site-Manager-Spec nennt `X-API-Key`), der
HTTPS-Port des UOS (11443) und ob ein View-Only-Key Schreibaufrufe ablehnt. Installer: UOS 5.1.42 linux-x64 aus
`fw-update.ui.com` (sha256 dort veröffentlicht).

## Trade-offs & Alternativen
- **Guard.HTTPClient nehmen:** Er ist schon GET/HEAD-only, folgt aber Redirects zum selben Ziel und kennt keine
  Pfadliste. Empfehlung: ein eigener kleiner Client über demselben Guard, mit `CheckRedirect` = Fehler und einer
  Pfadprüfung vor jedem Request. Er ist einzeln testbar, und eine spätere Lockerung des Guards wirkt nicht still auf
  UniFi.
- **Details rotierend über Läufe (Konzept):** braucht Zustand im Agent. Empfehlung: v1 fragt Details nur für Geräte,
  die offline sind (höchstens 8). Das reicht für die Ursache; PoE kommt später.

## Risiken & Rollback
- Der Key kann schreiben. Gegenmittel: Methode und Pfad werden vor jedem Request geprüft, Tests decken ab, dass
  `POST`/`DELETE`/fremde Pfade/Redirects nie gesendet werden, und der Key steht in keinem Fehler.
- `security` prüft jede Agent-Task.
- Rollback: Modul und Ansicht entfernen; keine Daten.

## Doku-Impact
Admin-Doku Monitoring: Modul, Key anlegen und hinterlegen, was gesendet wird, was nicht abgedeckt ist (DE+EN).
Entwickler-Doku Agent: Ansicht und UniFi-Client (DE+EN). Changelog-Fragment.

## Offene Fragen
Keine an Kevin. Kevin 2026-11-15: Zähler hier, Liste in R-1518; Lab-Test auf einer frisch installierten UOS-VM.
