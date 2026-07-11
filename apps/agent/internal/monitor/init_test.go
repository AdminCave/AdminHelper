// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"bytes"
	"encoding/pem"
	"net/http"
	"net/http/httptest"
	"testing"
)

// The blind --insecure init pins the presented server cert (TOFU) instead of
// persisting INSECURE=1 (3.2), so fetchServerCertPEM must return exactly the
// chain the server presented — otherwise the pin would trust the wrong cert.
func TestFetchServerCertPEMCapturesPresentedChain(t *testing.T) {
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {}))
	defer srv.Close()

	pemBytes, err := fetchServerCertPEM(srv.URL)
	if err != nil {
		t.Fatalf("fetchServerCertPEM: %v", err)
	}
	block, _ := pem.Decode(pemBytes)
	if block == nil {
		t.Fatal("no PEM block captured")
	}
	if !bytes.Equal(block.Bytes, srv.Certificate().Raw) {
		t.Fatal("captured cert does not match the server's presented cert")
	}
}

func TestFetchServerCertPEMUnreachable(t *testing.T) {
	// A closed port must surface an error, not a silent empty pin.
	if _, err := fetchServerCertPEM("https://127.0.0.1:1"); err == nil {
		t.Fatal("expected an error for an unreachable host")
	}
}
