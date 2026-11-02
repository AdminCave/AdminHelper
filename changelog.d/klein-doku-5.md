### Fixed

- **Doku: Keyring-Pruefung im Agent-Deployment (apt) liest den Primaer-Fingerprint:** Die Pruefsaetze in Schritt 1 und 1b (DE/EN) lesen den `fpr`-Record des Hauptschluessels und brechen bei einem Schluessel mit designiertem Widerrufer nicht mehr faelschlich ab.
- **Doku: Web-UI-Inaktivitaetswaechter nach Reload vollstaendig beschrieben:** Auch eine gespeicherte Zeit in der Zukunft oder ohne Zahl meldet sofort ab; nur eine fehlende Zeit zaehlt als Bedienung.
