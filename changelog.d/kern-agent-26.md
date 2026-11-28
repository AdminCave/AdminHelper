### Changed

- **Agent: Dienste unter FreeBSD seltener abgefragt:** Der Dienst-Block (`service -e` und je Skript `status`) wird
  hoechstens alle 15 Minuten neu gelesen, `service -e` nur nach einer Aenderung an rc.conf, rc.conf.d oder rc.d;
  dazwischen meldet der Agent den letzten Stand. Die beobachteten Dienste fragt jeder Lauf ab.
