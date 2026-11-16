### Changed

- **Monitoring: Verschachtelungstiefe begrenzt:** Der Monitoring-Dienst nimmt Request-Bodies und Agent-Reports nur bis
  zu 32 Ebenen Verschachtelung an; tiefer ist ein `422` mit der Stelle in `loc`.
