// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package httpclient

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/sha256"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"fmt"
	"math/big"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

// chainPair is an internal-PKI-like two-tier chain: a CA and a ServerAuth leaf
// signed by it — the shape the gateway presents ([leaf, intermediate]).
type chainPair struct {
	caDER   []byte
	leafDER []byte
	leafKey *ecdsa.PrivateKey
}

func makeChain(t *testing.T, cn string) chainPair {
	t.Helper()
	caKey, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	caTmpl := &x509.Certificate{
		SerialNumber:          big.NewInt(1),
		Subject:               pkix.Name{CommonName: cn + " CA"},
		NotBefore:             time.Now().Add(-time.Hour),
		NotAfter:              time.Now().Add(time.Hour),
		IsCA:                  true,
		KeyUsage:              x509.KeyUsageCertSign,
		BasicConstraintsValid: true,
	}
	caDER, err := x509.CreateCertificate(rand.Reader, caTmpl, caTmpl, &caKey.PublicKey, caKey)
	if err != nil {
		t.Fatal(err)
	}
	caCert, err := x509.ParseCertificate(caDER)
	if err != nil {
		t.Fatal(err)
	}

	leafKey, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	leafTmpl := &x509.Certificate{
		SerialNumber: big.NewInt(2),
		Subject:      pkix.Name{CommonName: cn},
		NotBefore:    time.Now().Add(-time.Hour),
		NotAfter:     time.Now().Add(time.Hour),
		KeyUsage:     x509.KeyUsageDigitalSignature,
		ExtKeyUsage:  []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth},
		DNSNames:     []string{"gateway.internal"}, // deliberately NOT the test host
	}
	leafDER, err := x509.CreateCertificate(rand.Reader, leafTmpl, caCert, &leafKey.PublicKey, caKey)
	if err != nil {
		t.Fatal(err)
	}
	return chainPair{caDER: caDER, leafDER: leafDER, leafKey: leafKey}
}

// serveChain starts a TLS server presenting exactly the given DER chain and
// reports via the returned flag whether a request ever REACHED the handler —
// the proof that a rejected handshake leaks no request bytes (the token).
func serveChain(t *testing.T, key *ecdsa.PrivateKey, chain ...[]byte) (*httptest.Server, *bool) {
	t.Helper()
	handled := false
	srv := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		handled = true
		w.WriteHeader(http.StatusOK)
	}))
	srv.TLS = &tls.Config{
		Certificates: []tls.Certificate{{Certificate: chain, PrivateKey: key}},
	}
	srv.StartTLS()
	t.Cleanup(srv.Close)
	return srv, &handled
}

func fpOf(der []byte) [sha256.Size]byte { return sha256.Sum256(der) }

func TestCAFingerprintAcceptsChainToPinnedCA(t *testing.T) {
	// The gateway shape: [leaf, ca] presented, the pin is the CA — and the leaf's
	// SAN does NOT match the connect host, which must not matter (pin = identity).
	c := makeChain(t, "gw")
	srv, handled := serveChain(t, c.leafKey, c.leafDER, c.caDER)

	client := NewCAFingerprint(fpOf(c.caDER), 5*time.Second)
	resp, err := client.Get(srv.URL)
	if err != nil {
		t.Fatalf("verifizierte Kette haette akzeptiert werden muessen: %v", err)
	}
	resp.Body.Close()
	if !*handled {
		t.Fatal("Request hat den Handler nie erreicht")
	}
}

func TestCAFingerprintRejectsForeignChainBeforeAnyRequest(t *testing.T) {
	// Server presents a chain under a DIFFERENT CA: the handshake must fail and
	// the handler must never run — no request byte (token) leaves the client.
	genuine := makeChain(t, "gw")
	foreign := makeChain(t, "mitm")
	srv, handled := serveChain(t, foreign.leafKey, foreign.leafDER, foreign.caDER)

	client := NewCAFingerprint(fpOf(genuine.caDER), 5*time.Second)
	if _, err := client.Get(srv.URL); err == nil {
		t.Fatal("fremde Kette haette abgelehnt werden muessen")
	}
	if *handled {
		t.Fatal("Handshake-Reject darf keinen Request durchlassen")
	}
}

func TestCAFingerprintRejectsAppendedCAWithoutChain(t *testing.T) {
	// Adversarial: an attacker APPENDS the genuine (public) CA cert to its own
	// leaf. The fingerprint IS present in the chain — but the leaf does not
	// chain to it, so the anchor verify must reject.
	genuine := makeChain(t, "gw")
	attacker := makeChain(t, "mitm")
	srv, handled := serveChain(t, attacker.leafKey, attacker.leafDER, genuine.caDER)

	client := NewCAFingerprint(fpOf(genuine.caDER), 5*time.Second)
	if _, err := client.Get(srv.URL); err == nil {
		t.Fatal("angehaengte CA ohne echte Signatur-Kette haette abgelehnt werden muessen")
	}
	if *handled {
		t.Fatal("Handshake-Reject darf keinen Request durchlassen")
	}
}

func TestCAFingerprintAcceptsDirectLeafPin(t *testing.T) {
	// Degenerate but valid: the pinned fingerprint is the presented leaf itself
	// (self-signed single-cert server) — a direct pin, nothing to chain.
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	tmpl := &x509.Certificate{
		SerialNumber:          big.NewInt(3),
		Subject:               pkix.Name{CommonName: "solo"},
		NotBefore:             time.Now().Add(-time.Hour),
		NotAfter:              time.Now().Add(time.Hour),
		KeyUsage:              x509.KeyUsageDigitalSignature | x509.KeyUsageCertSign,
		ExtKeyUsage:           []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth},
		BasicConstraintsValid: true,
	}
	der, err := x509.CreateCertificate(rand.Reader, tmpl, tmpl, &key.PublicKey, key)
	if err != nil {
		t.Fatal(err)
	}
	srv, handled := serveChain(t, key, der)

	client := NewCAFingerprint(fpOf(der), 5*time.Second)
	resp, err := client.Get(srv.URL)
	if err != nil {
		t.Fatalf("direkter Leaf-Pin haette akzeptiert werden muessen: %v", err)
	}
	resp.Body.Close()
	if !*handled {
		t.Fatal("Request hat den Handler nie erreicht")
	}
}

func TestParseCAFingerprint(t *testing.T) {
	c := makeChain(t, "gw")
	want := fpOf(c.caDER)
	hexUpperColons := ""
	for i, b := range want {
		if i > 0 {
			hexUpperColons += ":"
		}
		hexUpperColons += fmt.Sprintf("%02X", b)
	}

	ok := []string{
		fmt.Sprintf("%x", want),
		hexUpperColons,
		"sha256:" + fmt.Sprintf("%x", want),
		"  " + fmt.Sprintf("%x", want) + "  ",
	}
	for _, s := range ok {
		got, err := ParseCAFingerprint(s)
		if err != nil || got != want {
			t.Errorf("ParseCAFingerprint(%q) = %v/%v, erwartet Match", s, got, err)
		}
	}

	bad := []string{"", "abc", "zz" + fmt.Sprintf("%x", want)[2:], fmt.Sprintf("%x", want)[:62]}
	for _, s := range bad {
		if _, err := ParseCAFingerprint(s); err == nil {
			t.Errorf("ParseCAFingerprint(%q) haette fehlschlagen muessen", s)
		}
	}
}
