### Fixed

- **Monitoring: eine Entwarnung startet den Cooldown der Regel nicht mehr:** Faellt ein Check kurz nach der Recovery erneut aus, geht der Alert wieder raus.
- **Monitoring: Checks behalten ihren Takt:** Speichern eines Checks und ein Template-Sync verschieben seinen naechsten Lauf nicht mehr; nach einem Neustart des Dienstes laeuft jeder Check ein Intervall nach seinem letzten Lauf weiter, Ueberfaellige gleich.
- **Monitoring: Laengengrenzen fuer Server-IDs und Regelwerte:** Die Admin-API nimmt Server-IDs bis 255 Zeichen, Texte in Regeln bis 1024 Zeichen und Regel-Listen bis zur Feldgrenze an.
- **Monitoring: ein Check mit unpassenden Regeln haelt den Start nicht mehr auf:** Er bleibt eingefroren, die uebrigen bekommen ihre Regelschicht; zentrale Modul-Checks mit eigener Konfiguration bekommen wieder Update-Angebote ihres Moduls.
