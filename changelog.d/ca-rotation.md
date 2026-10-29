### Added

- **CA: Ablaufdaten anzeigen und Zwischenzertifikate unter derselben Root rotieren:**
  `docker compose run --rm --no-deps ca-issuer python -m app.cli status` zeigt Root, aktuelle und abgeloeste
  Zwischenzertifikate der internen CA mit Name, Ablaufdatum (UTC) und Resttagen; Exit 1, wenn die Root oder ein
  aktuelles Zwischenzertifikat weniger als 180 Tage hat, 3, wenn eins davon nicht gueltig oder eine der Dateien nicht
  lesbar ist, sonst 0. Exit 1 auch, wenn ein Eintrag der Datei `<scope>-retired.pem` (unten) kein Zwischenzertifikat
  seines Scopes unter der Root ist: Der Start ueberspringt ihn mit einer WARNING, `status` markiert ihn mit `SKIPPED`
  und dem Grund. `… python -m app.cli rotate-intermediates` stellt fuer `tunnel`, `access` und `internal` neue
  Zwischenzertifikate unter derselben Root aus (Name mit Datum, etwa `AdminHelper Access Intermediate 2031-05-04`);
  die abgeloesten bleiben ohne Schluessel in `<scope>-retired.pem` im Volume `ca-pki`, bis sie ablaufen. Die
  Root-Passphrase kommt wie beim Dienst aus `CA_ROOT_PASSPHRASE_FILE` bzw. `CA_ROOT_PASSPHRASE`, sonst aus einer
  Abfrage am Terminal oder der ersten Zeile von stdin, nie aus einem Argument; eine falsche Passphrase aendert nichts.
  Der Befehl laeuft auch, wenn der `ca-issuer` wegen abgelaufener Zwischenzertifikate nicht startet, und nennt danach
  den Neustart: erst `docker compose restart ca-issuer`, warten, bis `docker compose ps` ihn als `healthy` zeigt, dann
  `docker compose restart gateway`, denn das Gateway liest seine Zertifikate nur beim eigenen Start und soll sie erst
  lesen, nachdem der `ca-issuer` sie neu ausgestellt hat. Der Issuer signiert dann mit den neuen
  Zwischenzertifikaten und erneuert weiter Zertifikate der abgeloesten, Gateway (`client-ca.pem`) und frps (`ca.crt`)
  vertrauen alten und neuen, bis die alten ablaufen, und ihre Server-Zertifikate werden unter den neuen neu
  ausgestellt. Enrollte Agenten und Desktops erneuern wie bisher und uebernehmen dabei die neue Kette. Das Image des
  `ca-issuer` fuehrt dazu uebergebene Argumente als Nutzer `app` aus statt des Dienstes. Die Meldungen zum Ende eines
  Zwischenzertifikats (WARNING beim Start und beim Signieren, Abbruch beim Start, ERROR und HTTP 503 beim Signieren)
  nennen den Befehl; ist ein Zwischenzertifikat noch nicht gueltig, nennen sie stattdessen die Host-Uhr (NTP). Geht die
  Uhr des Hosts hinter dem Ausstellen eines aktuellen Zwischenzertifikats nach, bricht die Rotation ab und aendert
  nichts, denn unter dieser Uhr wuerde sie dem aktuellen Zwischenzertifikat nicht mehr vertrauen; die Meldung nennt
  Datei, Name und Beginn der Gueltigkeit. Doku: Betrieb (DE+EN).

### Changed

- **Desktop, Provisionierungs-Tab: `--ca-fp` ist der Fingerprint der Root der internen CA:** bisher der des
  access-Zwischenzertifikats, der mit dessen Rotation ungueltig wurde. Der neue Wert bleibt ueber eine Rotation
  der Zwischenzertifikate gueltig; aeltere Befehle gelten bis zur naechsten Rotation. Desktop und Server zusammen
  aktualisieren: der Befehl eines neuen Desktops scheitert gegen einen Server, dessen Kette die Root nicht
  enthaelt, mit der Fingerprint-Meldung. Mit `--ca-fp` auf die Root nimmt der Agent nur ein Server-Zertifikat des
  `access`-Zwischenzertifikats an, nicht eins eines anderen Scopes unter derselben Root. Doku: Agent-Deployment,
  Betrieb (DE+EN).
- **Gateway: sendet die Root der internen CA in seiner Zertifikatskette mit (R-0667):** Auf `:443`, `:8444` und
  `:8445` schickt das Gateway nach seinem Server-Zertifikat und dem `access`-Zwischenzertifikat jetzt auch die Root
  (`gateway-fullchain.pem`); frps schickt weiter nur Server- und Zwischenzertifikat. So kann der Agent mit `--ca-fp`
  den Fingerprint der Root pinnen, der eine Rotation der Zwischenzertifikate uebersteht; ein Wert mit dem Fingerprint
  des Zwischenzertifikats passt weiter, bis es rotiert wird. Ein vorhandenes Gateway-Zertifikat ohne Root stellt der
  `ca-issuer` bei seinem naechsten Start mit neuem Schluessel neu aus. Das Gateway liest seine Zertifikate nur beim
  eigenen Start und hat sie beim Update schon gelesen, bevor der `ca-issuer` sie neu ausstellt: Nach dem Update auf
  diese Version einmal `docker compose restart gateway`, sobald `docker compose ps` den `ca-issuer` als `healthy`
  zeigt; bis dahin sendet das Gateway die Root nicht. Ein Desktop, der vor seiner Registrierung dem selbstsignierten
  Zertifikat des Gateways vertraut hat, bestaetigt das neue einmal. Ein voller TLS-Handshake wird rund 430 Byte
  groesser.
