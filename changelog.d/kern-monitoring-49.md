### Fixed

- **Monitoring: Glocke beim Loeschen ueber Vorlage oder Server:** wer eine Vorlage loescht, ihre Zuweisung aufhebt, eine
  Check-Definition aus ihr entfernt oder einen Server loescht, schliesst jetzt wie beim Loeschen eines einzelnen Checks
  den offenen Vorfall der Glocke; vorher blieb er offen. Ein Check, den ein Modul-Fund "verschwunden" abschaltet,
  bekommt seine Entwarnung vom Nachhol-Job.
- **Monitoring: keine Glocken-Meldung bei geaenderter Schwere:** wer die Schwere eines Checks aendert, waehrend sein
  Alarm offen ist, loest im Nachhol-Job keine Meldung mehr aus.
