### Added

- **Monitoring: zentrale Checks (Typ `central`):** der Monitoring-Dienst prueft oeffentliche Endpunkte selbst von
  aussen, mit sieben Fuehlern: `tls` (Kette, Name nach RFC 9525, Restlaufzeit relativ zur Laufzeit,
  ACME-Erneuerungsfenster, CAA), `dns` (oeffentliche Resolver, Basislinie, Delegation, DNSSEC), `rdap` (Status und Ablauf der
  Domain; `.de` nur Status), `smtp` und `imap` (Zertifikat und STARTTLS, nur Begruessung, hoechstens alle 15 min je
  Adresse und Port), `mail_dns` (MX, FCrDNS, SPF, DMARC, MTA-STS, TLS-RPT) und `dnsbl` (freie Blocklisten, Spamhaus
  nur mit eigenem DQS-Schluessel). Der Dienst verbindet sich nur mit oeffentlichen Adressen; ein internes Ziel meldet
  der Check als `unknown` fuer den Agent. Ein Probe-Check des Agents als Partner erklaert ein rotes Ergebnis (Weg
  oder Dienst) und erkennt ein erneuertes Zertifikat ohne Reload. Zentrale Checks legt ein Admin an, nicht ein
  Template.
- **Desktop: zentrale Checks anlegen:** Typ `central` mit Fuehler, Agent-Partner und "Basislinie neu lernen"; die
  Zertifikatsansicht zeigt zentrale `tls`- und `rdap`-Zeilen mit der neuen Spalte Quelle.
- **Monitoring-API: `POST /checks/{check_id}/rebaseline`** verwirft die gelernte Basislinie eines zentralen
  `dns`-Checks.
- **Konfiguration: `MONITOR_PUBLIC_RESOLVERS`** (Standard `9.9.9.9,1.1.1.1`) und **`MONITOR_SPAMHAUS_DQS_KEY`**
  (leer: Spamhaus aus). Doku: Monitoring, Installation, API-Referenz (DE+EN).

### Security

- **Monitoring: Check-Ergebnisse vor dem Speichern bereinigt:** Meldung und Details jedes Checks werden vor dem
  Speichern auf Zeichen gebracht, die die Datenbank speichert.
