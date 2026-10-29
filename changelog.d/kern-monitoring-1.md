### Fixed

- **Monitoring HTTP-Check: Content-Encoding-Schichten begrenzt:** Ein Check liest hoechstens fuenf gzip- oder
  deflate-Schichten, wie urllib3; mehr meldet er als `unknown` ("Too many content encodings (>5)").
