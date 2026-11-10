### Changed

- **Vorfaelle: hoechstens 200 Eintraege von Hand:** Notiz und Wieder oeffnen antworten 409, sobald ein Vorfall 200
  Eintraege von Hand traegt (Notizen, Bestaetigen, Beheben, Wieder oeffnen); Bestaetigen und Beheben bleiben moeglich.

### Fixed

- **Eskalation: ein Rueckfall auf warning stoppt die Frist:** ein Vorfall, der vor Ablauf der Eskalationsfrist auf
  warning zurueckfaellt, eskaliert nicht mehr als kritisch; ein erneutes critical beginnt eine neue Frist, nach der
  auch eskaliert, wer schon eine Nachricht bekam.
