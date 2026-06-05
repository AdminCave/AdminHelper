// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package provision

import (
	"bytes"
	"encoding/json"
	"encoding/pem"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
)

// TOFU (GHSA-wv93): a --insecure provisioning call must capture the certificate
// the server actually presented, so the recurring loop can pin it instead of
// disabling TLS verification forever.
func TestCallActivateCapturesServerCert(t *testing.T) {
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !strings.HasSuffix(r.URL.Path, "/provision/activate") {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"serverName": "s", "apiKey": "k"})
	}))
	defer srv.Close()

	resp, certPEM, err := callActivate(srv.URL, "tok", "srv-1", "", true)
	if err != nil {
		t.Fatalf("callActivate: %v", err)
	}
	if resp.APIKey != "k" {
		t.Fatalf("apiKey = %q", resp.APIKey)
	}
	if len(certPEM) == 0 || !strings.Contains(string(certPEM), "BEGIN CERTIFICATE") {
		t.Fatal("Server-Zertifikat wurde nicht erfasst")
	}
	// The captured cert must be exactly what the server presented.
	block, _ := pem.Decode(certPEM)
	if block == nil || !bytes.Equal(block.Bytes, srv.Certificate().Raw) {
		t.Fatal("erfasstes Zertifikat passt nicht zum Server-Zertifikat")
	}
}

// writePinnedCert must produce a readable file containing the chain.
func TestWritePinnedCert(t *testing.T) {
	pemData := []byte("-----BEGIN CERTIFICATE-----\nabc\n-----END CERTIFICATE-----\n")
	path, err := writePinnedCert(pemData)
	if err != nil {
		t.Fatalf("writePinnedCert: %v", err)
	}
	defer func() { _ = os.Remove(path) }()
	got, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("ReadFile: %v", err)
	}
	if !bytes.Equal(got, pemData) {
		t.Fatalf("pinned cert content mismatch")
	}
}
