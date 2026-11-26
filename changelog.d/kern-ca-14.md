### Changed

- The ca-issuer reads the client certificate headers only from requests that come straight from the gateway,
  like the server; uvicorn in the ca-issuer no longer evaluates forwarded headers.
