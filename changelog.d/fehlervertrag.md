### Added

- **Server: Fehlerantworten tragen ein optionales Feld `code` neben `detail`:** ein stabiler Maschinencode der
  Form `ERR_...`, an dem ein Client verzweigt statt am Text. Heute tragen ihn die 403 der Zertifikatspruefung
  (`ERR_CERT_REVOKED`, `ERR_CERT_USER_MISMATCH`, `ERR_CERT_SERVER_MISMATCH`); `detail` bleibt unveraendert,
  alle anderen Fehler bleiben ohne `code`. Doku: API-Referenz fuer Entwickler (DE+EN).

### Changed

- **Desktop: Anmeldung zeigt den Text des Servers:** Lehnt der Server die Anmeldung ab, zeigt der Desktop
  dessen Text statt `Login fehlgeschlagen (<Status>): <roher Body>`; Status und Code reichen strukturiert bis
  ins UI. Gegen einen Server ohne Feld `code` gelten die Zertifikatscodes am Anfang von `detail` weiter.
- **Web: Fehlertext ohne Maschinencode:** Schickt der Server zu einem Fehler ein `code` (`ERR_...`), zeigt das
  Web den Text ohne das Praefix `ERR_...:` und haelt den Code in `ApiError.code` fest. Doku: Web-UI fuer
  Entwickler (DE+EN).

### Fixed

- **Desktop: kein Monitoring-Fehler nach dem Ende der Sitzung:** Nach dem Ende der Sitzung meldet das
  Monitoring des Desktops keinen Fehler mehr in der Statusleiste; die Anmeldung erscheint wie bisher.
- **Desktop: Hilfen der Anmeldung nur nach dem Code:** Die Hilfen des Anmeldebildschirms — Vertrauensdialog,
  Pin oder Geraete-Identitaet zuruecksetzen, Geraet registrieren, die Hinweise zum Zertifikat des Geraets
  (anderer Benutzer, nicht mehr gueltig) — richten sich nur nach dem Code des Fehlers;
  ein Text, der einen Code nur enthaelt, loest keine mehr aus.
- **Desktop: Fehlertext des Servers statt rohem Body:** Lehnt der Server eine Anfrage des Desktops ab, zeigt die
  Statusleiste dessen Text (`detail`), bei 422 die Feldmeldungen, statt `HTTP <Status>: <roher Body>`; ohne
  lesbaren Text `HTTP <Status>`. Status und Code reichen strukturiert bis ins UI. Doku: Desktop fuer Entwickler
  (DE+EN).
