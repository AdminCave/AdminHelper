### Changed

- **Gateway auf nginx 1.30:** das Gateway-Image baut auf dem Stable-Zweig nginx 1.30.6 statt 1.29 (Mainline); die
  Konfiguration bleibt unveraendert.
- **Python 3.14 in den Images:** Server, Monitoring und CA-Issuer laufen auf python:3.14-slim statt 3.12; die
  gehashten Locks sind unter 3.14 neu erzeugt (dieselben Versionen), die CI testet 3.14 und 3.15.
