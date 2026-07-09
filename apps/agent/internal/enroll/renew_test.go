// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package enroll

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/json"
	"encoding/pem"
	"math/big"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"
	"time"
)

// selfSigned builds a self-signed leaf + PKCS#8 key PEM with the given validity.
func selfSigned(t *testing.T, cn string, notBefore, notAfter time.Time) (certPEM, keyPEM []byte) {
	t.Helper()
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	tmpl := &x509.Certificate{
		SerialNumber:          big.NewInt(1),
		Subject:               pkix.Name{CommonName: cn},
		NotBefore:             notBefore,
		NotAfter:              notAfter,
		KeyUsage:              x509.KeyUsageDigitalSignature,
		BasicConstraintsValid: true,
	}
	der, err := x509.CreateCertificate(rand.Reader, tmpl, tmpl, &key.PublicKey, key)
	if err != nil {
		t.Fatal(err)
	}
	certPEM = pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der})
	keyDER, _ := x509.MarshalPKCS8PrivateKey(key)
	keyPEM = pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: keyDER})
	return certPEM, keyPEM
}

func TestNeedsRenewal(t *testing.T) {
	now := time.Now()
	day := 24 * time.Hour
	cases := []struct {
		name          string
		before, after time.Time
		wantDue       bool
	}{
		{"fresh 11pct", now.Add(-10 * day), now.Add(80 * day), false},
		{"just past half", now.Add(-46 * day), now.Add(44 * day), true},
		{"well past half", now.Add(-80 * day), now.Add(10 * day), true},
		{"degenerate window", now, now, true},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			certPEM, _ := selfSigned(t, "x", tc.before, tc.after)
			due, err := NeedsRenewal(certPEM, RenewalFraction)
			if err != nil {
				t.Fatalf("NeedsRenewal: %v", err)
			}
			if due != tc.wantDue {
				t.Fatalf("due = %v, erwartet %v", due, tc.wantDue)
			}
		})
	}
}

func TestNeedsRenewalRejectsGarbage(t *testing.T) {
	if _, err := NeedsRenewal([]byte("nope"), RenewalFraction); err == nil {
		t.Fatal("erwartet Fehler bei Nicht-PEM")
	}
}

func TestServerClientFallsBackWhenNotProvisioned(t *testing.T) {
	dir := t.TempDir() // empty -> not provisioned
	client, err := ServerClient(dir, "", true, time.Second)
	if err != nil || client == nil {
		t.Fatalf("Fallback-Client erwartet, err=%v", err)
	}
}

func TestServerClientUsesIdentityWhenProvisioned(t *testing.T) {
	dir := t.TempDir()
	now := time.Now()
	certPEM, keyPEM := selfSigned(t, "agent", now.Add(-time.Hour), now.Add(time.Hour))
	mustWrite(t, CertPath(dir), certPEM)
	mustWrite(t, KeyPath(dir), keyPEM)
	mustWrite(t, CAPath(dir), certPEM) // any valid CA bundle
	if !Provisioned(dir) {
		t.Fatal("sollte provisioned sein")
	}
	client, err := ServerClient(dir, "", false, time.Second)
	if err != nil || client == nil {
		t.Fatalf("mTLS-Client erwartet, err=%v", err)
	}
}

// TestRenewSwapsIdentity drives a real renewal against a TLS test server: the
// agent presents its current cert (mTLS), the server returns a new fullchain,
// and Renew must persist it (new key + cert).
func TestRenewSwapsIdentity(t *testing.T) {
	dir := t.TempDir()
	now := time.Now()
	certPEM, keyPEM := selfSigned(t, "agent", now.Add(-time.Hour), now.Add(time.Hour))
	mustWrite(t, CertPath(dir), certPEM)
	mustWrite(t, KeyPath(dir), keyPEM)

	// Enforce mTLS: the server must actually demand + verify the agent's client cert, so a
	// regression where the client stops presenting it (or falls into the legacy fallback) fails the
	// handshake instead of staying green (6.13). The agent cert is self-signed, so it is its own
	// client CA.
	pool := x509.NewCertPool()
	if !pool.AppendCertsFromPEM(certPEM) {
		t.Fatal("Agent-Cert nicht als Client-CA ladbar")
	}
	srv := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/ca/renew" {
			t.Errorf("Pfad = %q, erwartet /ca/renew", r.URL.Path)
		}
		if len(r.TLS.PeerCertificates) == 0 {
			t.Error("Server sah kein Client-Zertifikat (mTLS nicht präsentiert)")
		}
		var body RenewRequest
		_ = json.NewDecoder(r.Body).Decode(&body)
		if body.CSR == "" {
			t.Error("CSR fehlt im Renew-Body")
		}
		_ = json.NewEncoder(w).Encode(IssueResponse{
			Cert: "new-leaf", Fullchain: "new-leaf+int", Chain: "int+root",
		})
	}))
	srv.TLS = &tls.Config{ClientAuth: tls.RequireAndVerifyClientCert, ClientCAs: pool}
	srv.StartTLS()
	defer srv.Close()

	// Trust the test server's own cert (so the client verifies it under custom-root).
	srvCertPEM := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: srv.Certificate().Raw})
	mustWrite(t, CAPath(dir), srvCertPEM)

	if err := Renew(dir, srv.URL, 5*time.Second); err != nil {
		t.Fatalf("Renew: %v", err)
	}

	if got, _ := os.ReadFile(CertPath(dir)); string(got) != "new-leaf+int" {
		t.Fatalf("agent.crt = %q, erwartet new-leaf+int", string(got))
	}
	if got, _ := os.ReadFile(KeyPath(dir)); string(got) == string(keyPEM) {
		t.Fatal("Key wurde nicht rotiert")
	}
}

// TestServerClientMTLSPresentationVsFallback proves the security-critical property directly: the
// provisioned client presents its cert and is accepted by an mTLS-enforcing server, while the
// fallback (unprovisioned) client — which presents no client cert — is rejected at the handshake.
// A plain `client != nil` assertion cannot tell these two apart (6.13).
func TestServerClientMTLSPresentationVsFallback(t *testing.T) {
	dir := t.TempDir()
	now := time.Now()
	certPEM, keyPEM := selfSigned(t, "agent", now.Add(-time.Hour), now.Add(time.Hour))
	mustWrite(t, CertPath(dir), certPEM)
	mustWrite(t, KeyPath(dir), keyPEM)

	pool := x509.NewCertPool()
	if !pool.AppendCertsFromPEM(certPEM) {
		t.Fatal("Agent-Cert nicht als Client-CA ladbar")
	}
	srv := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	srv.TLS = &tls.Config{ClientAuth: tls.RequireAndVerifyClientCert, ClientCAs: pool}
	srv.StartTLS()
	defer srv.Close()
	srvCertPEM := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: srv.Certificate().Raw})
	mustWrite(t, CAPath(dir), srvCertPEM)

	// Provisioned client presents the agent cert -> accepted.
	client, err := ServerClient(dir, "", false, 5*time.Second)
	if err != nil {
		t.Fatalf("ServerClient (provisioned): %v", err)
	}
	resp, err := client.Get(srv.URL)
	if err != nil {
		t.Fatalf("provisionierter Client abgelehnt: %v", err)
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("Status = %d, erwartet 200", resp.StatusCode)
	}

	// Fallback client (unprovisioned dir, insecure so it trusts the server cert) presents no client
	// cert -> the mTLS server rejects the handshake.
	fallback, err := ServerClient(t.TempDir(), "", true, 5*time.Second)
	if err != nil {
		t.Fatalf("ServerClient (fallback): %v", err)
	}
	if _, err := fallback.Get(srv.URL); err == nil {
		t.Fatal("Fallback-Client ohne Client-Cert wurde akzeptiert — erwartet Handshake-Fehler")
	}
}

func mustWrite(t *testing.T, path string, data []byte) {
	t.Helper()
	if err := os.WriteFile(path, data, 0600); err != nil {
		t.Fatal(err)
	}
}

func TestMaybeRenewSkipsWhenNotProvisioned(t *testing.T) {
	orig := renewFunc
	called := false
	renewFunc = func(string, string, time.Duration) error { called = true; return nil }
	t.Cleanup(func() { renewFunc = orig })

	done, err := MaybeRenew(t.TempDir(), "https://x", time.Second)
	if err != nil || done {
		t.Fatalf("not provisioned -> (false, nil), got (%v, %v)", done, err)
	}
	if called {
		t.Error("renewFunc darf bei nicht-provisioniert nicht laufen")
	}
}

func TestMaybeRenewSkipsWhenNotDue(t *testing.T) {
	orig := renewFunc
	called := false
	renewFunc = func(string, string, time.Duration) error { called = true; return nil }
	t.Cleanup(func() { renewFunc = orig })

	dir := t.TempDir()
	now := time.Now()
	day := 24 * time.Hour
	certPEM, keyPEM := selfSigned(t, "agent", now.Add(-10*day), now.Add(80*day)) // 11% through -> not due
	mustWrite(t, CertPath(dir), certPEM)
	mustWrite(t, KeyPath(dir), keyPEM)

	done, err := MaybeRenew(dir, "https://x", time.Second)
	if err != nil || done {
		t.Fatalf("not due -> (false, nil), got (%v, %v)", done, err)
	}
	if called {
		t.Error("renewFunc darf bei nicht-faelligem Cert nicht laufen")
	}
}

func TestMaybeRenewRenewsWhenDue(t *testing.T) {
	orig := renewFunc
	called := false
	renewFunc = func(string, string, time.Duration) error { called = true; return nil }
	t.Cleanup(func() { renewFunc = orig })

	dir := t.TempDir()
	now := time.Now()
	day := 24 * time.Hour
	certPEM, keyPEM := selfSigned(t, "agent", now.Add(-80*day), now.Add(10*day)) // well past half -> due
	mustWrite(t, CertPath(dir), certPEM)
	mustWrite(t, KeyPath(dir), keyPEM)

	done, err := MaybeRenew(dir, "https://x", time.Second)
	if err != nil || !done {
		t.Fatalf("due -> (true, nil), got (%v, %v)", done, err)
	}
	if !called {
		t.Error("renewFunc muss bei faelligem Cert laufen")
	}
}

func TestLeafExpired(t *testing.T) {
	now := time.Now()

	valid, _ := selfSigned(t, "agent", now.Add(-time.Hour), now.Add(time.Hour))
	if exp, _, err := leafExpired(valid); err != nil || exp {
		t.Errorf("gueltiges Leaf: expired=%v err=%v, want false/nil", exp, err)
	}

	stale, _ := selfSigned(t, "agent", now.Add(-2*time.Hour), now.Add(-time.Hour))
	exp, notAfter, err := leafExpired(stale)
	if err != nil || !exp {
		t.Errorf("abgelaufenes Leaf: expired=%v err=%v, want true/nil", exp, err)
	}
	if notAfter.After(now) {
		t.Errorf("abgelaufenes Leaf: notAfter %v sollte in der Vergangenheit liegen", notAfter)
	}

	if _, _, err := leafExpired([]byte("kein PEM")); err == nil {
		t.Error("Muell-PEM: want error, got nil")
	}
}
