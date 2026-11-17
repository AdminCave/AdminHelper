### Changed

- **Server-API: vier 422 in der Form des Schemas:** Ein leerer Name einer Verbindung ohne Server, nicht lesbares
  YAML eines Playbooks (Anlegen und Aendern) und ein von der SSRF-Sperre abgewiesenes Ziel im Testversand antworten
  mit `detail[]` (`loc`, `msg`, `type`, `input`) wie jede andere Validierung statt mit `detail` als Text; der Text
  steht in `msg`.
