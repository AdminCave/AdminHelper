### Changed

- **CI: schnellere Laeufe:** Die Server-Tests laufen je Python-Version in vier statt zwei Shards; ein CI-Lauf und
  ein Lauf der Merge Queue brauchen damit etwa die Haelfte der Zeit. Eine Session reiht ihren Pull Request gleich
  nach den Pruefungen ein (Auto-Merge, gebunden an den geprueften Stand), und `scripts/dev/queue-wait.sh` meldet rote
  Checks eines wartenden Pull Requests sofort statt erst nach der Zeitueberschreitung.
