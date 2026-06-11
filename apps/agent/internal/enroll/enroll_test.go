// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package enroll

import (
	"crypto/elliptic"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"testing"

	"crypto/x509"
	"encoding/pem"
)

func TestGenerateKeyIsP256(t *testing.T) {
	key, err := GenerateKey()
	if err != nil {
		t.Fatalf("GenerateKey: %v", err)
	}
	if key.Curve != elliptic.P256() {
		t.Fatalf("erwartet P-256, bekam %v", key.Curve.Params().Name)
	}
}

func TestBuildCSRRoundtrips(t *testing.T) {
	key, _ := GenerateKey()
	csrPEM, err := BuildCSR(key, "srv-123")
	if err != nil {
		t.Fatalf("BuildCSR: %v", err)
	}
	block, _ := pem.Decode(csrPEM)
	if block == nil || block.Type != "CERTIFICATE REQUEST" {
		t.Fatalf("kein CSR-PEM: %q", string(csrPEM))
	}
	csr, err := x509.ParseCertificateRequest(block.Bytes)
	if err != nil {
		t.Fatalf("CSR parsen: %v", err)
	}
	if csr.Subject.CommonName != "srv-123" {
		t.Fatalf("CN = %q, erwartet srv-123", csr.Subject.CommonName)
	}
	if err := csr.CheckSignature(); err != nil {
		t.Fatalf("CSR-Signatur ungueltig: %v", err)
	}
}

func TestSubmitParsesIssueResponse(t *testing.T) {
	want := IssueResponse{Cert: "C", Fullchain: "leaf+int", Chain: "int+root"}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Content-Type") != "application/json" {
			t.Errorf("Content-Type fehlt: %q", r.Header.Get("Content-Type"))
		}
		var got EnrollRequest
		_ = json.NewDecoder(r.Body).Decode(&got)
		if got.Token != "tok" || got.CSR != "csr-pem" {
			t.Errorf("Body falsch: %+v", got)
		}
		_ = json.NewEncoder(w).Encode(want)
	}))
	defer srv.Close()

	got, err := Submit(srv.Client(), srv.URL, EnrollRequest{Token: "tok", CSR: "csr-pem"})
	if err != nil {
		t.Fatalf("Submit: %v", err)
	}
	if got.Fullchain != want.Fullchain || got.Chain != want.Chain {
		t.Fatalf("Antwort falsch: %+v", got)
	}
}

func TestSubmitRejectsHTTPError(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "bad token", http.StatusForbidden)
	}))
	defer srv.Close()
	if _, err := Submit(srv.Client(), srv.URL, EnrollRequest{}); err == nil {
		t.Fatal("erwartet Fehler bei HTTP 403")
	}
}

func TestSubmitRejectsIncompleteResponse(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// leaf only, no fullchain/chain -> unusable
		_ = json.NewEncoder(w).Encode(IssueResponse{Cert: "leaf"})
	}))
	defer srv.Close()
	if _, err := Submit(srv.Client(), srv.URL, EnrollRequest{}); err == nil {
		t.Fatal("erwartet Fehler bei unvollstaendiger Antwort")
	}
}

func TestStoreAndProvisioned(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "identity") // not pre-created -> Store must mkdir
	if Provisioned(dir) {
		t.Fatal("frisches Verzeichnis darf nicht provisioned sein")
	}

	key, _ := GenerateKey()
	resp := &IssueResponse{Cert: "leaf", Fullchain: "leaf+int", Chain: "int+root"}
	if err := Store(dir, key, resp); err != nil {
		t.Fatalf("Store: %v", err)
	}
	if !Provisioned(dir) {
		t.Fatal("nach Store muss provisioned sein")
	}

	if b, _ := os.ReadFile(CertPath(dir)); string(b) != "leaf+int" {
		t.Fatalf("agent.crt = %q, erwartet fullchain", string(b))
	}
	if b, _ := os.ReadFile(CAPath(dir)); string(b) != "int+root" {
		t.Fatalf("ca.crt = %q, erwartet chain", string(b))
	}
	// The key must be a parseable EC PKCS#8 PEM.
	keyBytes, _ := os.ReadFile(KeyPath(dir))
	block, _ := pem.Decode(keyBytes)
	if block == nil {
		t.Fatal("agent.key ist kein PEM")
	}
	if _, err := x509.ParsePKCS8PrivateKey(block.Bytes); err != nil {
		t.Fatalf("agent.key nicht parsebar: %v", err)
	}

	// The private key must not be world-readable (POSIX only).
	if runtime.GOOS != "windows" {
		info, _ := os.Stat(KeyPath(dir))
		if perm := info.Mode().Perm(); perm != 0600 {
			t.Fatalf("agent.key Perm = %o, erwartet 600", perm)
		}
	}
}
