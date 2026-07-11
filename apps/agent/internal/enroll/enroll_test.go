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
	"strings"
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
		var got Request
		_ = json.NewDecoder(r.Body).Decode(&got)
		if got.Token != "tok" || got.CSR != "csr-pem" {
			t.Errorf("Body falsch: %+v", got)
		}
		_ = json.NewEncoder(w).Encode(want)
	}))
	defer srv.Close()

	got, err := Submit(srv.Client(), srv.URL, Request{Token: "tok", CSR: "csr-pem"})
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
	if _, err := Submit(srv.Client(), srv.URL, Request{}); err == nil {
		t.Fatal("erwartet Fehler bei HTTP 403")
	}
}

func TestSubmitRejectsIncompleteResponse(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// leaf only, no fullchain/chain -> unusable
		_ = json.NewEncoder(w).Encode(IssueResponse{Cert: "leaf"})
	}))
	defer srv.Close()
	if _, err := Submit(srv.Client(), srv.URL, Request{}); err == nil {
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

// TestStoreStagesBeforeCommit reproduces the F5 lockout window: a renewal mints a
// NEW key, so a crash between writing the key and the cert must NOT leave a new
// key paired with the old cert (the mismatch breaks mTLS → silent lockout, ADR
// 0001 §3.3). The staged write keeps the live identity untouched until the
// atomic commit, so an interrupted renew leaves the consistent old pair.
func TestStoreStagesBeforeCommit(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "identity")

	keyA, _ := GenerateKey()
	respA := &IssueResponse{Cert: "leafA", Fullchain: "fullA", Chain: "chainA"}
	if err := Store(dir, keyA, respA); err != nil {
		t.Fatalf("Store A: %v", err)
	}
	keyABytes, _ := os.ReadFile(KeyPath(dir))

	// Stage a renewal (new key + new cert) but do NOT commit — this is the
	// power-loss-before-rename window.
	keyB, _ := GenerateKey()
	respB := &IssueResponse{Cert: "leafB", Fullchain: "fullB", Chain: "chainB"}
	commit, err := stageIdentity(dir, keyB, respB)
	if err != nil {
		t.Fatalf("stageIdentity B: %v", err)
	}

	// Before the commit the live identity must still be the consistent A pair.
	if b, _ := os.ReadFile(CertPath(dir)); string(b) != "fullA" {
		t.Fatalf("vor commit: agent.crt = %q, erwartet fullA", string(b))
	}
	if b, _ := os.ReadFile(KeyPath(dir)); string(b) != string(keyABytes) {
		t.Fatal("vor commit: agent.key wurde bereits veraendert (Mismatch-Fenster!)")
	}

	// The commit swaps atomically to B.
	if err := commit(); err != nil {
		t.Fatalf("commit B: %v", err)
	}
	if b, _ := os.ReadFile(CertPath(dir)); string(b) != "fullB" {
		t.Fatalf("nach commit: agent.crt = %q, erwartet fullB", string(b))
	}
	if b, _ := os.ReadFile(CAPath(dir)); string(b) != "chainB" {
		t.Fatalf("nach commit: ca.crt = %q, erwartet chainB", string(b))
	}

	// No staging leftovers in the identity dir.
	entries, _ := os.ReadDir(dir)
	for _, e := range entries {
		if strings.HasSuffix(e.Name(), tmpSuffix) {
			t.Fatalf("Staging-Datei nicht aufgeraeumt: %s", e.Name())
		}
	}
}

// TestStageIdentityCleansUpStagedTempsOnWriteError pins the best-effort cleanup (enroll.go 174-177):
// if a later staging write fails, the temps already written must be removed so no .tmp corpses linger
// to confuse the next renewal (6.98).
func TestStageIdentityCleansUpStagedTempsOnWriteError(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "identity")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}

	key, _ := GenerateKey()
	resp := &IssueResponse{Cert: "leaf", Fullchain: "full", Chain: "chain"}

	// Block the SECOND staging write (agent.crt.tmp) by pre-creating its target as a directory, so
	// OpenFile fails. The first write (agent.key.tmp) succeeds and must then be cleaned up.
	if err := os.Mkdir(CertPath(dir)+tmpSuffix, 0o755); err != nil {
		t.Fatal(err)
	}

	if _, err := stageIdentity(dir, key, resp); err == nil {
		t.Fatal("erwartet Schreibfehler, wenn der cert-Temp-Pfad ein Verzeichnis ist")
	}

	// The already-written key temp must be gone — no .tmp leftovers after the aborted staging.
	if _, statErr := os.Stat(KeyPath(dir) + tmpSuffix); !os.IsNotExist(statErr) {
		t.Errorf("agent.key.tmp muss nach dem Schreibfehler aufgeraeumt sein, stat err = %v", statErr)
	}
}
