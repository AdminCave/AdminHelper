### Added

- **Desktop: Serverseite im Monitoring:** je Server eine Karte je Dienst oder Modul; gruene und wartende Karten
  bleiben zu, Probleme stehen offen. Die Karte „Neu gefunden" uebernimmt oder verwirft die Funde des Agents direkt
  auf der Seite, „Jetzt scannen" fordert eine neue Erkennung an, und eine Karte nennt, warum ihre Checks gerade
  schweigen (stiller Check, Wartungsfenster, Host down). Die Karte „System" traegt den Verlauf von CPU, RAM,
  Platten, Load und Netz.
- **Desktop: Monitoring-Kosten je Server:** eine Karte zeigt je Collector des Agents Dauer und CPU-Zeit eines Laufs,
  gemittelt ueber die letzte Stunde, die Zeitlimit-Treffer dieser Stunde und ob die Selbstdrosselung ihn seltener
  laufen laesst (`GET /api/monitoring/status/server/{server_id}/costs`).
- **Desktop: Querschnitt ueber alle Server:** die Reiter „Zertifikate & Domains" (Ablauf der Zertifikate aus
  HTTPS-Checks und den Fuehlern `tls` und `certfile`), „Backups" (Proxmox-Backups je VM), „Updates & Neustarts"
  (Neustart noetig, offene Sicherheits-Updates je Linux-Server) und „Funde" (der Eingang aller Server, nach Server
  gruppiert).
- **Desktop: Warnung ohne Ergebnis:** kommt laenger als `max(10 min, 2 × kuerzestes Check-Intervall)` kein
  Check-Ergebnis, warnen Statusleiste und Monitoring-Seite.
- **Desktop: Zugangsdaten hinterlegen:** meldet ein Modul-Check `no_credential` oder `denied`, oeffnet ein Knopf auf
  seiner Karte ein Terminal zum Host, in dem nur `sudo adminhelper-agent monitor credential set <ref>` laeuft; das
  Geheimnis wird nur dort eingegeben, AdminHelper behaelt es nicht. Ohne SSH-Verbindung oder auf Windows zeigt der
  Dialog den Befehl zum Kopieren.
- **Monitoring-API:** die Status-Routen nennen je Check den Grund einer Unterdrueckung (`mutedReason`), Check- und
  Status-API den Katalog-Schluessel eines Modul-Checks (`moduleCheckKey`), `GET /status/summary` das juengste
  Ergebnis (`lastResultAt`) und das kuerzeste Intervall (`minIntervalS`); der HTTP-Check legt mit `verify_ssl` das
  Zertifikat des ersten HTTPS-Hops in seine Details (Gueltigkeit, Aussteller, Name).
