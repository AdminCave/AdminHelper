### Added

- **Desktop: alle Dienste eines Servers:** die Monitoring-Ansicht eines Servers zeigt das ganze Dienste-Inventar, das
  der Agent meldet — Zustand, seit wann, Neustarts, RAM und Grund eines Ausfalls —, sortierbar, mit einem Filter
  nach Zustand und einer Suche ueber alle Spalten samt Aliasen. Nur fuer Admins.
- **Agent: Zustandsfakten der Dienste:** unter Linux ein gebuendeltes `systemctl show` je Lauf (Unterzustand,
  Ergebnis, Exit-Status oder Signal, Neustarts, seit wann, RAM); unter Windows der Exit-Code aus `sc query` und, nur
  bei einem gestoppten Dienst mit Fehler, die Absturz-Ereignisse 7031/7034 des Service Control Manager der letzten
  24 h. Der Report traegt die neuen Felder im Inventar und `systemd.failed_details`; aeltere Monitoring-Dienste
  ignorieren sie.
- **Monitoring: Grund eines Ausfalls in der Meldung:** ein fehlgeschlagener Dienst nennt in Meldung, Mail und
  Webhook seinen Grund, etwa `Failed: nginx.service (exit-code, status=1)`; im Modus `list` steht er hinter jedem
  Dienst, der nicht laeuft, unter Windows der Fehlercode aus `sc query` (`Spooler (win32=1067)`). Der Text bleibt
  waehrend desselben Ausfalls gleich.
- **Monitoring: Fehlerzeilen fehlgeschlagener Dienste:** der Dienst speichert bis zu 10 Fehlerzeilen je
  fehlgeschlagenem Dienst, vor dem Speichern geschwaerzt (Passwoerter in URLs, `password=`/`token=`/`secret=`/`key=`,
  `Authorization`, lange Hex- und Base64-Folgen), nur solange der Dienst fehlschlaegt und nur fuer Admins im
  Desktop; nie in Meldung, Verlauf, Mail oder Webhook. Der Schalter "Fehlerzeilen senden" je Server (ab Werk an)
  loescht sie beim Ausschalten. Der Agent dieser Version sammelt noch keine Zeilen.
- **Desktop: "Mehr Log":** je systemd-Dienst oeffnet ein Knopf einen Terminal-Tab ueber die gespeicherte
  SSH-Verbindung des Servers mit `journalctl --no-pager --unit=<unit> --lines=200`, mit den Rechten des
  SSH-Benutzers; gespeichert wird nichts. Doku: Monitoring (Admin und Entwickler), Agent, API-Referenz (DE+EN).
