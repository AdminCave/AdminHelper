### Added

- **Agent nennt unter Last die auffaelligsten Prozesse:** ab 80 % CPU oder RAM schickt der Ressourcen-Block je
  hoechstens fuenf Prozesse mit der hoechsten CPU-Last und dem hoechsten RAM-Verbrauch (Name, PID, Anteil bzw. Bytes,
  nie die Befehlszeile); der Desktop zeigt sie, solange `agent_resources` warnt.
