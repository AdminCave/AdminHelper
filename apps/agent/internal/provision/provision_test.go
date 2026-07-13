// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package provision

import (
	"bytes"
	"crypto/sha256"
	"encoding/json"
	"encoding/pem"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"strconv"
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
		// The X-Provision-Token header is the ONLY auth for the activate call; pin it here so a
		// refactor that drops it fails this test instead of every production provisioning (6.23).
		if r.Header.Get("X-Provision-Token") != "tok" {
			http.Error(w, "missing provision token", http.StatusUnauthorized)
			return
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"serverName": "s", "apiKey": "k"})
	}))
	defer srv.Close()

	// callActivate rewrites the host's port to the enroll plane; the httptest
	// server is on a random port, so pass that port through unchanged.
	u, _ := url.Parse(srv.URL)
	port, _ := strconv.Atoi(u.Port())
	resp, certPEM, err := callActivate(srv.URL, "tok", "srv-1", "", true, nil, port)
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

func TestMonitorBaseURL(t *testing.T) {
	// 2.70: derive the push base from the provisioned server URL + the
	// server-declared relative path; nil/absolute values fall back to the
	// well-known path.
	relPath := "/api/mon2"
	absURL := "https://old.example/monitoring"
	wellKnown := "/api/monitoring"
	cases := []struct {
		name       string
		monitorURL *string
		want       string
	}{
		{"nil -> well-known", nil, "https://srv/api/monitoring"},
		{"relative path used", &relPath, "https://srv/api/mon2"},
		{"absolute value -> fallback", &absURL, "https://srv/api/monitoring"},
		{"explicit well-known", &wellKnown, "https://srv/api/monitoring"},
	}
	for _, c := range cases {
		if got := monitorBaseURL("https://srv", c.monitorURL); got != c.want {
			t.Errorf("%s: monitorBaseURL = %q, want %q", c.name, got, c.want)
		}
	}
}

func TestEnrollEndpoint(t *testing.T) {
	// Pure host/port rewrite: swap in the enroll port, drop path+query, and keep IPv6 literals
	// bracketed (Hostname() strips the brackets, JoinHostPort re-adds them) (6.22).
	cases := []struct {
		url  string
		port int
		want string
	}{
		{"https://example.com", 8444, "https://example.com:8444/enroll"},
		{"https://example.com:8443/api?x=1", 8444, "https://example.com:8444/enroll"},
		{"https://[::1]:8443/api", 8444, "https://[::1]:8444/enroll"},
	}
	for _, c := range cases {
		got, err := enrollEndpoint(c.url, c.port)
		if err != nil || got != c.want {
			t.Errorf("enrollEndpoint(%q, %d) = %q/%v, erwartet %q", c.url, c.port, got, err, c.want)
		}
	}
	if _, err := enrollEndpoint("://kaputt", 1); err == nil {
		t.Error("ungueltige URL haette Fehler ergeben muessen")
	}
	if _, err := enrollEndpoint("/no-host", 1); err == nil {
		t.Error("URL ohne Host haette Fehler ergeben muessen")
	}
}

func TestCallActivateRejectsConsumedToken(t *testing.T) {
	// A consumed/invalid provision token -> the server answers 403; callActivate must surface an
	// error, not treat the empty body as a successful activation (6.23).
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		http.Error(w, "token bereits verwendet", http.StatusForbidden)
	}))
	defer srv.Close()
	u, _ := url.Parse(srv.URL)
	port, _ := strconv.Atoi(u.Port())
	if _, _, err := callActivate(srv.URL, "used", "srv-1", "", true, nil, port); err == nil {
		t.Fatal("403 (verbrauchter Token) haette einen Fehler ergeben muessen")
	}
}

func TestRunRejectsCAFPCombinedWithOtherTrust(t *testing.T) {
	// One trust source per call: --ca-fp must not be silently weakened by
	// --insecure or diluted by --cacert. Validation fails BEFORE any network I/O
	// (the URL is unroutable on purpose — reaching it would hang/fail differently).
	if err := Run("https://192.0.2.1", "tok", "srv-1", "", true, "ab"); err == nil ||
		!strings.Contains(err.Error(), "--ca-fp") {
		t.Fatalf("--ca-fp + --insecure haette die Kombi-Validierung treffen muessen, war: %v", err)
	}
	if err := Run("https://192.0.2.1", "tok", "srv-1", "/tmp/ca.pem", false, "ab"); err == nil ||
		!strings.Contains(err.Error(), "--ca-fp") {
		t.Fatalf("--ca-fp + --cacert haette die Kombi-Validierung treffen muessen, war: %v", err)
	}
	// A malformed fingerprint must also die before any network I/O.
	if err := Run("https://192.0.2.1", "tok", "srv-1", "", false, "nicht-hex"); err == nil ||
		!strings.Contains(err.Error(), "SHA-256") {
		t.Fatalf("kaputter Fingerprint haette die Parse-Validierung treffen muessen, war: %v", err)
	}
}

func TestPinVerifiedAnchorWritesOnlyTheAnchor(t *testing.T) {
	// The pinned file must contain EXACTLY the fingerprint-matched cert — pinning
	// the whole presented chain would anchor the rotating leaf too, defeating the
	// point of a CA pin.
	leafPEM := []byte("-----BEGIN CERTIFICATE-----\nbGVhZg==\n-----END CERTIFICATE-----\n")
	caPEM := []byte("-----BEGIN CERTIFICATE-----\nY2E=\n-----END CERTIFICATE-----\n")
	chain := append(append([]byte{}, leafPEM...), caPEM...)

	caBlock, _ := pem.Decode(caPEM)
	fp := sha256.Sum256(caBlock.Bytes)

	path, _, err := pinVerifiedAnchor(chain, fp)
	if err != nil {
		t.Fatalf("pinVerifiedAnchor: %v", err)
	}
	defer os.Remove(path)
	got, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	blocks := 0
	rest := got
	for {
		var b *pem.Block
		b, rest = pem.Decode(rest)
		if b == nil {
			break
		}
		blocks++
		if sha256.Sum256(b.Bytes) != fp {
			t.Fatal("gepinnter Block ist nicht der Anchor")
		}
	}
	if blocks != 1 {
		t.Fatalf("erwartet genau 1 gepinntes Zertifikat, war %d", blocks)
	}

	// Fingerprint not present in the chain -> fail closed.
	var wrong [sha256.Size]byte
	if _, _, err := pinVerifiedAnchor(chain, wrong); err == nil {
		t.Fatal("fehlender Anchor haette einen Fehler ergeben muessen")
	}
}

func TestCallActivateRejectsBadJSON(t *testing.T) {
	// A 200 with an unparseable body must not be swallowed as a success (6.23).
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte("{not json"))
	}))
	defer srv.Close()
	u, _ := url.Parse(srv.URL)
	port, _ := strconv.Atoi(u.Port())
	if _, _, err := callActivate(srv.URL, "tok", "srv-1", "", true, nil, port); err == nil {
		t.Fatal("kaputtes JSON haette einen Fehler ergeben muessen")
	}
}
