// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package selfupdate

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"math/big"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"

	"adminhelper-agent/internal/enroll"
)

// gatewayPKI is the trust of an enrolled agent in small: a CA named like the access
// intermediate, whose leaf the gateway serves on :8445, and an agent identity.
type gatewayPKI struct {
	caPEM, leafPEM, leafKeyPEM, agentPEM, agentKeyPEM []byte
}

func newGatewayPKI(t *testing.T) gatewayPKI {
	t.Helper()
	return newPKIOf(t, "AdminHelper Access Intermediate")
}

// newPKIOf is newGatewayPKI with a CA of the given common name.
func newPKIOf(t *testing.T, caCN string) gatewayPKI {
	t.Helper()
	caKey := newKey(t)
	now := time.Now()
	caTmpl := &x509.Certificate{
		SerialNumber: big.NewInt(1), Subject: pkix.Name{CommonName: caCN},
		NotBefore: now.Add(-time.Hour), NotAfter: now.Add(time.Hour),
		IsCA: true, BasicConstraintsValid: true, KeyUsage: x509.KeyUsageCertSign,
	}
	caDER, err := x509.CreateCertificate(rand.Reader, caTmpl, caTmpl, &caKey.PublicKey, caKey)
	if err != nil {
		t.Fatal(err)
	}
	ca, _ := x509.ParseCertificate(caDER)
	leafKey := newKey(t)
	leafDER, err := x509.CreateCertificate(rand.Reader, &x509.Certificate{
		SerialNumber: big.NewInt(2), Subject: pkix.Name{CommonName: "gateway"},
		NotBefore: now.Add(-time.Hour), NotAfter: now.Add(time.Hour),
		IPAddresses: []net.IP{net.ParseIP("127.0.0.1")},
		ExtKeyUsage: []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth},
	}, ca, &leafKey.PublicKey, caKey)
	if err != nil {
		t.Fatal(err)
	}
	agentKey := newKey(t)
	agentDER, err := x509.CreateCertificate(rand.Reader, &x509.Certificate{
		SerialNumber: big.NewInt(3), Subject: pkix.Name{CommonName: "agent"},
		NotBefore: now.Add(-time.Hour), NotAfter: now.Add(time.Hour),
		ExtKeyUsage: []x509.ExtKeyUsage{x509.ExtKeyUsageClientAuth},
	}, ca, &agentKey.PublicKey, caKey)
	if err != nil {
		t.Fatal(err)
	}
	return gatewayPKI{
		caPEM: certPEM(caDER), leafPEM: certPEM(leafDER), leafKeyPEM: keyPEM(t, leafKey),
		agentPEM: certPEM(agentDER), agentKeyPEM: keyPEM(t, agentKey),
	}
}

func newKey(t *testing.T) *ecdsa.PrivateKey {
	t.Helper()
	k, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	return k
}

func certPEM(der []byte) []byte {
	return pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der})
}

func keyPEM(t *testing.T, k *ecdsa.PrivateKey) []byte {
	t.Helper()
	der, err := x509.MarshalECPrivateKey(k)
	if err != nil {
		t.Fatal(err)
	}
	return pem.EncodeToMemory(&pem.Block{Type: "EC PRIVATE KEY", Bytes: der})
}

// repoPlane serves the leaf like the gateway's certless :8445.
func repoPlane(t *testing.T, p gatewayPKI) string {
	t.Helper()
	cert, err := tls.X509KeyPair(p.leafPEM, p.leafKeyPEM)
	if err != nil {
		t.Fatal(err)
	}
	srv := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {}))
	srv.TLS = &tls.Config{Certificates: []tls.Certificate{cert}}
	srv.StartTLS()
	t.Cleanup(srv.Close)
	return srv.URL
}

func writeFile(t *testing.T, path string, data []byte) {
	t.Helper()
	if err := os.WriteFile(path, data, 0o600); err != nil {
		t.Fatal(err)
	}
}

func TestUpdateClientTrustsTheEnrolledCA(t *testing.T) {
	p := newGatewayPKI(t)
	url := repoPlane(t, p)
	dir := t.TempDir()
	writeFile(t, enroll.CertPath(dir), p.agentPEM)
	writeFile(t, enroll.KeyPath(dir), p.agentKeyPEM)
	writeFile(t, enroll.CAPath(dir), p.caPEM)

	// No pinned cacert in the config: only the enrolled CA can make the gateway's leaf valid.
	client, err := updateClient(dir, "", false, 5*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	resp, err := client.Get(url)
	if err != nil {
		t.Fatalf("the repo plane's leaf of the enrolled CA was refused: %v", err)
	}
	resp.Body.Close()
}

func TestUpdateClientWithoutIdentityKeepsTheConfiguredTrust(t *testing.T) {
	p := newGatewayPKI(t)
	url := repoPlane(t, p)

	client, err := updateClient(t.TempDir(), "", false, 5*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	if resp, err := client.Get(url); err == nil {
		resp.Body.Close()
		t.Fatal("a leaf of a CA the host does not trust was accepted")
	}

	cacert := t.TempDir() + "/ca.crt"
	writeFile(t, cacert, p.caPEM)
	client, err = updateClient(t.TempDir(), cacert, false, 5*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	resp, err := client.Get(url)
	if err != nil {
		t.Fatalf("the configured cacert was not used: %v", err)
	}
	resp.Body.Close()
}

// enrolled writes p's agent identity and CA bundle as the enrollment leaves them.
func enrolled(t *testing.T, p gatewayPKI) string {
	t.Helper()
	dir := t.TempDir()
	writeFile(t, enroll.CertPath(dir), p.agentPEM)
	writeFile(t, enroll.KeyPath(dir), p.agentKeyPEM)
	writeFile(t, enroll.CAPath(dir), p.caPEM)
	return dir
}

// R-1769: on an enrolled host only the enrolled CA counts; a configured insecure or cacert
// must not open the update to another server.
func TestUpdateClientOfAnEnrolledHostIgnoresInsecureAndCacert(t *testing.T) {
	own, foreign := newGatewayPKI(t), newGatewayPKI(t)
	ownURL, foreignURL := repoPlane(t, own), repoPlane(t, foreign)
	dir := enrolled(t, own)
	cacert := t.TempDir() + "/ca.crt"
	writeFile(t, cacert, foreign.caPEM)

	for _, tc := range []struct {
		name     string
		cacert   string
		insecure bool
	}{{"insecure", "", true}, {"cacert", cacert, false}, {"both", cacert, true}} {
		client, err := updateClient(dir, tc.cacert, tc.insecure, 5*time.Second)
		if err != nil {
			t.Fatal(err)
		}
		if resp, err := client.Get(foreignURL); err == nil {
			resp.Body.Close()
			t.Fatalf("%s: a server outside the enrolled CA was accepted", tc.name)
		}
		resp, err := client.Get(ownURL)
		if err != nil {
			t.Fatalf("%s: the enrolled gateway was refused: %v", tc.name, err)
		}
		resp.Body.Close()
	}
}

// R-1769: a leaf that the enrolled bundle verifies but that is not issued by the access
// intermediate (the frps leaf of the tunnel intermediate, say) is not the gateway.
func TestUpdateClientOfAnEnrolledHostRefusesALeafOfAnotherIssuer(t *testing.T) {
	p := newPKIOf(t, "AdminHelper Tunnel Intermediate")
	url := repoPlane(t, p)
	client, err := updateClient(enrolled(t, p), "", false, 5*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	resp, err := client.Get(url)
	if err == nil {
		resp.Body.Close()
		t.Fatal("a leaf of the tunnel intermediate passed as the gateway")
	}
	if !strings.Contains(err.Error(), "not issued by the access intermediate") {
		t.Fatalf("refused for another reason: %v", err)
	}
}
