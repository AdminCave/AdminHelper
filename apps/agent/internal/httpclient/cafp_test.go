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
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
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

// makeChain builds a chain whose leaf names gateway.internal and 127.0.0.1, the
// httptest host.
func makeChain(t *testing.T, cn string) chainPair {
	t.Helper()
	return makeChainWithIPs(t, cn, net.IPv4(127, 0, 0, 1))
}

// makeChainWithIPs is makeChain with the leaf's IP SANs given; its DNS SAN stays
// gateway.internal.
func makeChainWithIPs(t *testing.T, cn string, ips ...net.IP) chainPair {
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
		DNSNames:     []string{"gateway.internal"}, // never the test host, which is an IP
		IPAddresses:  ips,
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

// hostOf is the host the client connects to, as provision takes it from --url.
func hostOf(t *testing.T, srv *httptest.Server) string {
	t.Helper()
	u, err := url.Parse(srv.URL)
	if err != nil {
		t.Fatal(err)
	}
	return u.Hostname()
}

func TestCAFingerprintAcceptsChainToPinnedCA(t *testing.T) {
	// The gateway shape: [leaf, ca] presented, the pin is the CA, and the leaf names
	// the connect host among other names, as every later call requires.
	c := makeChain(t, "gw")
	srv, handled := serveChain(t, c.leafKey, c.leafDER, c.caDER)

	client := NewCAFingerprint(fpOf(c.caDER), hostOf(t, srv), 5*time.Second)
	resp, err := client.Get(srv.URL)
	if err != nil {
		t.Fatalf("verifizierte Kette haette akzeptiert werden muessen: %v", err)
	}
	resp.Body.Close()
	if !*handled {
		t.Fatal("Request hat den Handler nie erreicht")
	}
}

// threeTier is the internal CA's shape: root, a scope intermediate under it and a
// ServerAuth leaf (naming 127.0.0.1) issued by that intermediate.
type threeTier struct {
	rootDER, interDER, leafDER []byte
	leafKey                    *ecdsa.PrivateKey
}

func makeThreeTier(t *testing.T, interCN string) threeTier {
	t.Helper()
	issue := func(tmpl, parent *x509.Certificate, pub *ecdsa.PublicKey, signer *ecdsa.PrivateKey) (*x509.Certificate, []byte) {
		der, err := x509.CreateCertificate(rand.Reader, tmpl, parent, pub, signer)
		if err != nil {
			t.Fatal(err)
		}
		c, err := x509.ParseCertificate(der)
		if err != nil {
			t.Fatal(err)
		}
		return c, der
	}
	newKey := func() *ecdsa.PrivateKey {
		k, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
		if err != nil {
			t.Fatal(err)
		}
		return k
	}
	caTmpl := func(serial int64, cn string) *x509.Certificate {
		return &x509.Certificate{
			SerialNumber:          big.NewInt(serial),
			Subject:               pkix.Name{CommonName: cn},
			NotBefore:             time.Now().Add(-time.Hour),
			NotAfter:              time.Now().Add(time.Hour),
			IsCA:                  true,
			KeyUsage:              x509.KeyUsageCertSign,
			BasicConstraintsValid: true,
		}
	}
	rootKey, interKey, leafKey := newKey(), newKey(), newKey()
	rootTmpl := caTmpl(1, "AdminHelper Root CA")
	root, rootDER := issue(rootTmpl, rootTmpl, &rootKey.PublicKey, rootKey)
	inter, interDER := issue(caTmpl(2, interCN), root, &interKey.PublicKey, rootKey)
	_, leafDER := issue(&x509.Certificate{
		SerialNumber: big.NewInt(3),
		Subject:      pkix.Name{CommonName: "gateway"},
		NotBefore:    time.Now().Add(-time.Hour),
		NotAfter:     time.Now().Add(time.Hour),
		KeyUsage:     x509.KeyUsageDigitalSignature,
		ExtKeyUsage:  []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth},
		IPAddresses:  []net.IP{net.IPv4(127, 0, 0, 1)},
	}, inter, &leafKey.PublicKey, interKey)
	return threeTier{rootDER: rootDER, interDER: interDER, leafDER: leafDER, leafKey: leafKey}
}

func TestCAFingerprintRootPinAcceptsAnAccessIntermediateLeaf(t *testing.T) {
	for _, cn := range []string{"AdminHelper Access Intermediate", "AdminHelper Access Intermediate 2031-05-04"} {
		c := makeThreeTier(t, cn)
		srv, handled := serveChain(t, c.leafKey, c.leafDER, c.interDER, c.rootDER)
		resp, err := NewCAFingerprint(fpOf(c.rootDER), hostOf(t, srv), 5*time.Second).Get(srv.URL)
		if err != nil {
			t.Fatalf("%s: Leaf des access-Intermediates haette akzeptiert werden muessen: %v", cn, err)
		}
		resp.Body.Close()
		if !*handled {
			t.Fatalf("%s: Request hat den Handler nie erreicht", cn)
		}
	}
}

func TestCAFingerprintRootPinRejectsALeafOfAnotherScope(t *testing.T) {
	c := makeThreeTier(t, "AdminHelper Tunnel Intermediate")
	srv, handled := serveChain(t, c.leafKey, c.leafDER, c.interDER, c.rootDER)
	_, err := NewCAFingerprint(fpOf(c.rootDER), hostOf(t, srv), 5*time.Second).Get(srv.URL)
	if err == nil {
		t.Fatal("Leaf des tunnel-Intermediates haette abgelehnt werden muessen")
	}
	if !strings.Contains(err.Error(), "not issued by the access intermediate") {
		t.Fatalf("Fehlertext nennt das access-Intermediate nicht: %v", err)
	}
	if *handled {
		t.Fatal("Request hat den Handler trotz Ablehnung erreicht")
	}
}

func TestCAFingerprintAccessIntermediatePinStillWorks(t *testing.T) {
	c := makeThreeTier(t, "AdminHelper Access Intermediate")
	srv, _ := serveChain(t, c.leafKey, c.leafDER, c.interDER)
	resp, err := NewCAFingerprint(fpOf(c.interDER), hostOf(t, srv), 5*time.Second).Get(srv.URL)
	if err != nil {
		t.Fatalf("aelterer Pin auf das access-Intermediate haette passen muessen: %v", err)
	}
	resp.Body.Close()
}

func TestCAFingerprintRejectsForeignChainBeforeAnyRequest(t *testing.T) {
	// Server presents a chain under a DIFFERENT CA: the handshake must fail and
	// the handler must never run — no request byte (token) leaves the client.
	genuine := makeChain(t, "gw")
	foreign := makeChain(t, "mitm")
	srv, handled := serveChain(t, foreign.leafKey, foreign.leafDER, foreign.caDER)

	client := NewCAFingerprint(fpOf(genuine.caDER), hostOf(t, srv), 5*time.Second)
	_, err := client.Get(srv.URL)
	if err == nil {
		t.Fatal("fremde Kette haette abgelehnt werden muessen")
	}
	if !strings.Contains(err.Error(), "expected CA fingerprint") {
		t.Fatalf("error = %v, want the missing fingerprint as the reason", err)
	}
	if *handled {
		t.Fatal("Handshake-Reject darf keinen Request durchlassen")
	}
}

func TestCAFingerprintRejectsAppendedCAWithoutChain(t *testing.T) {
	// Adversarial: an attacker APPENDS the genuine (public) CA cert to its own
	// leaf. The fingerprint IS present in the chain — but the leaf does not
	// chain to it, so the anchor verify must reject. The attacker's leaf does not
	// name the host either: the chain is checked first, so the error never offers
	// the names of a foreign leaf as the way out.
	genuine := makeChain(t, "gw")
	attacker := makeChainWithIPs(t, "mitm")
	srv, handled := serveChain(t, attacker.leafKey, attacker.leafDER, genuine.caDER)

	client := NewCAFingerprint(fpOf(genuine.caDER), hostOf(t, srv), 5*time.Second)
	_, err := client.Get(srv.URL)
	if err == nil {
		t.Fatal("angehaengte CA ohne echte Signatur-Kette haette abgelehnt werden muessen")
	}
	if !strings.Contains(err.Error(), "does not verify against the pinned CA") || strings.Contains(err.Error(), "EXTRA_SANS") {
		t.Fatalf("error = %v, want the broken chain as the reason, not the hostname", err)
	}
	if *handled {
		t.Fatal("Handshake-Reject darf keinen Request durchlassen")
	}
}

func TestCAFingerprintRejectsALeafThatDoesNotNameTheHost(t *testing.T) {
	// The leaf chains to the pinned CA but names only gateway.internal, while the
	// client connects via 127.0.0.1: every later call would reject it, so the first
	// contact does too, before a request (the token) leaves the client.
	c := makeChainWithIPs(t, "gw")
	srv, handled := serveChain(t, c.leafKey, c.leafDER, c.caDER)

	client := NewCAFingerprint(fpOf(c.caDER), hostOf(t, srv), 5*time.Second)
	_, err := client.Get(srv.URL)
	if err == nil {
		t.Fatal("a leaf that does not name the connect host was accepted")
	}
	for _, want := range []string{"does not name 127.0.0.1", "gateway.internal", "EXTRA_SANS"} {
		if !strings.Contains(err.Error(), want) {
			t.Errorf("error = %v, want it to contain %q", err, want)
		}
	}
	if *handled {
		t.Fatal("a request reached the handler despite the rejected handshake")
	}
}

// makeSoloCert is a self-signed single-cert server for the httptest host, valid
// from notBefore to notAfter.
func makeSoloCert(t *testing.T, notBefore, notAfter time.Time) ([]byte, *ecdsa.PrivateKey) {
	t.Helper()
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	tmpl := &x509.Certificate{
		SerialNumber:          big.NewInt(3),
		Subject:               pkix.Name{CommonName: "solo"},
		NotBefore:             notBefore,
		NotAfter:              notAfter,
		KeyUsage:              x509.KeyUsageDigitalSignature | x509.KeyUsageCertSign,
		ExtKeyUsage:           []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth},
		BasicConstraintsValid: true,
		IPAddresses:           []net.IP{net.IPv4(127, 0, 0, 1)}, // the httptest host
	}
	der, err := x509.CreateCertificate(rand.Reader, tmpl, tmpl, &key.PublicKey, key)
	if err != nil {
		t.Fatal(err)
	}
	return der, key
}

func TestCAFingerprintAcceptsDirectLeafPin(t *testing.T) {
	// Degenerate but valid: the pinned fingerprint is the presented leaf itself
	// (self-signed single-cert server) — a direct pin, nothing to chain.
	der, key := makeSoloCert(t, time.Now().Add(-time.Hour), time.Now().Add(time.Hour))
	srv, handled := serveChain(t, key, der)

	client := NewCAFingerprint(fpOf(der), hostOf(t, srv), 5*time.Second)
	resp, err := client.Get(srv.URL)
	if err != nil {
		t.Fatalf("direkter Leaf-Pin haette akzeptiert werden muessen: %v", err)
	}
	resp.Body.Close()
	if !*handled {
		t.Fatal("Request hat den Handler nie erreicht")
	}
}

func TestCAFingerprintRejectsADirectPinOutsideItsValidity(t *testing.T) {
	// The direct pin is held to the certificate's validity like a chain to the
	// pinned CA: an expired or not yet valid pinned leaf fails before a request.
	now := time.Now()
	for name, span := range map[string][2]time.Time{
		"expired":       {now.Add(-2 * time.Hour), now.Add(-time.Hour)},
		"not yet valid": {now.Add(time.Hour), now.Add(2 * time.Hour)},
	} {
		t.Run(name, func(t *testing.T) {
			der, key := makeSoloCert(t, span[0], span[1])
			srv, handled := serveChain(t, key, der)

			client := NewCAFingerprint(fpOf(der), hostOf(t, srv), 5*time.Second)
			_, err := client.Get(srv.URL)
			if err == nil {
				t.Fatal("a pinned leaf outside its validity was accepted")
			}
			if !strings.Contains(err.Error(), "pinned certificate") {
				t.Errorf("error = %v, want it to name the pinned certificate", err)
			}
			if *handled {
				t.Fatal("a request reached the handler despite the rejected handshake")
			}
		})
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
