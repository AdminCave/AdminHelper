<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Test fixtures — disposable TLS certificates

Two distinct self-signed certificates (`certA`/`certB`) plus their EC P-256
private keys (`keyA`/`keyB`, PKCS#8 DER), `CN=localhost`,
`SAN=DNS:localhost,IP:127.0.0.1`.

Used only by the real-handshake TOFU test in `src/tofu.rs`: an in-process
`tokio-rustls` server presents one of them so the test can prove the pinning
verifier accepts the pinned certificate and rejects a changed one.

These are **throwaway test material with no production value** — intentionally
committed so the test needs no certificate-generation dependency. Regenerate
(if ever needed) with:

```sh
openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes \
  -keyout key.pem -out cert.pem -days 3650 -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
openssl x509  -in cert.pem -outform DER -out certX.der
openssl pkcs8 -topk8 -nocrypt -in key.pem -outform DER -out keyX.der
```
