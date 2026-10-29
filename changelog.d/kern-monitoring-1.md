### Fixed

- **Monitoring HTTP-Check: Content-Encoding-Schichten begrenzt:** Ein Check liest hoechstens fuenf gzip- oder
  deflate-Schichten, wie urllib3; mehr meldet er als `unknown` ("Too many content encodings (>5)").
- **Monitoring HTTP-Check: Redirect ohne Location:** Ein 3xx ohne `Location`-Header meldet `critical`
  "Redirect without Location header" statt "Too many redirects (>5)".
