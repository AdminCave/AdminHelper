### Changed

- **Server-API: Namensfehler von `/api/servers` in der Form des Schemas:** lehnt `POST` oder `PUT /api/servers`
  einen Namen ab (`:`, ein Windows-Geraetename, `name: null` im `PUT`), steht der Grund jetzt wie bei den anderen
  Routen in `detail[]` mit `loc` `["body", "name"]` statt als Text in `detail`. Web und Desktop zeigen denselben
  Text wie bisher; eigene Skripte, die `detail` als Text lesen, nehmen nun `detail[0].msg`. Doku: API-Referenz
  (DE+EN).
