### Changed

- **Stack: Redis im eigenen internen Netz:** `redis` ist nur noch fuer `server` und `scheduler` erreichbar und
  startet ohne die zusaetzlichen Module des Images. Eigene Dienste, die Redis nutzen, muessen ins Netz `redis`.
- **Server: keine Proxy-Header in uvicorn:** uvicorn wertet `X-Forwarded-*` nicht mehr aus; die Client-Adresse
  bestimmt der Server weiter ueber `TRUSTED_PROXIES`.
