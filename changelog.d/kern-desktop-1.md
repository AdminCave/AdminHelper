### Changed

- **Desktop: Verbindungslisten hoechstens 16 MiB:** Der Abgleich mit dem Server und mit einer Sync-Quelle liest
  die Liste der Verbindungen bis 16 MiB, wie ein Playbook; eine groessere Antwort ist ein Fehler, und die
  bisherigen Verbindungen bleiben.
- **Desktop: Client-Cache nach einem Identitaetswechsel:** Wechselt die Geraete-Identitaet oder ein gepinntes
  Zertifikat, waehrend ein HTTP-Client entsteht, behaelt der Desktop diesen Client nicht im Cache; die naechste
  Anfrage baut ihn neu.
- **Desktop: RDP-Start nach Ablauf der Frist:** Ist die Zeit fuer den Verbindungsaufbau schon abgelaufen, startet
  der Desktop keine Anmeldepruefung mehr und meldet die Zeitueberschreitung.
