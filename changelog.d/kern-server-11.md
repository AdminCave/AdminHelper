### Changed

- **Neue Benutzer auf einem Weg:** `POST /api/users`, der Bootstrap, `python -m app.cli create-admin` und der Admin aus
  `ADMIN_PASSWORD` beim Start legen Benutzer jetzt ueber denselben Dienst an. Dadurch feuern auch Bootstrap und
  Start-Admin das Ereignis `user.created`, alle vier Wege gleichen die FRP-Policy ab, und der Start-Admin bekommt einen
  Audit-Eintrag.
