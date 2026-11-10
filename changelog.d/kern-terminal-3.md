### Fixed

- **Desktop: Dateien-Panel wartet auf die Anmeldung:** Steht die SSH-Sitzung noch an der Anmeldung, wartet das
  Panel *Dateien* darauf (hoechstens zwei Minuten) statt zu scheitern; danach laedt *Aktualisieren* erneut.
- **Desktop: Downloads im Dateien-Panel:** Die Teildatei eines Downloads wird exklusiv neu angelegt, und der
  vorgeschlagene Dateiname ist bereinigt.
- **Desktop: Sitzungsverlauf des AdminHelper-Terminals:** Eine SSH-Sitzung im eingebetteten Terminal endet ihren
  Eintrag unter *Letzte Sitzungen*, wenn ihr Programm endet oder der Tab geschlossen wird, und zeigt eine Dauer.
- **Desktop: Programmsuche:** Der Desktop sucht `ssh`, `xfreerdp` und `ansible-playbook` nur in absoluten
  PATH-Eintraegen; das eingebettete Terminal startet nur aus dem Hauptfenster oder einem losgeloesten
  Terminal-Fenster.
