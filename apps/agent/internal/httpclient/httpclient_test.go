// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package httpclient

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"errors"
	"math/big"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestDoReturnsBodyOn2xx(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("ok-body"))
	}))
	defer srv.Close()

	req, _ := http.NewRequest("GET", srv.URL, nil)
	body, err := Do(srv.Client(), req)
	if err != nil {
		t.Fatalf("Do gab Fehler: %v", err)
	}
	if string(body) != "ok-body" {
		t.Errorf("body = %q, erwartet %q", body, "ok-body")
	}
}

func TestDoMapsErrorStatusWithBody(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
		_, _ = w.Write([]byte("boom"))
	}))
	defer srv.Close()

	req, _ := http.NewRequest("GET", srv.URL, nil)
	body, err := Do(srv.Client(), req)
	if err == nil {
		t.Fatal("erwartet Fehler bei HTTP 500")
	}
	if body != nil {
		t.Errorf("body = %q, erwartet nil bei Fehler", body)
	}
	// The consolidated helper carries both status and body (the drift 2.5 fixed:
	// the old monitor push dropped the body).
	if !strings.Contains(err.Error(), "500") || !strings.Contains(err.Error(), "boom") {
		t.Errorf("Fehler %q enthaelt nicht Status+Body", err.Error())
	}
}

func TestDoMarks4xxAuthErrorsPermanent(t *testing.T) {
	// 4.80/4.81: 401/403/404 mean the agent's credentials or identity are the problem
	// (rotated/revoked key, deleted server) — a retry won't help, so a oneshot must
	// surface it (errors.Is ErrPermanent) and exit non-zero.
	for _, code := range []int{http.StatusUnauthorized, http.StatusForbidden, http.StatusNotFound} {
		srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			w.WriteHeader(code)
		}))
		req, _ := http.NewRequest("GET", srv.URL, nil)
		_, err := Do(srv.Client(), req)
		srv.Close()
		if !errors.Is(err, ErrPermanent) {
			t.Errorf("HTTP %d: errors.Is(err, ErrPermanent) = false, want true (err=%v)", code, err)
		}
	}
}

func TestDoTreats5xxAsTransient(t *testing.T) {
	// A 500 is transient — the oneshot logs it and stays green so the next run retries;
	// it must NOT be flagged permanent.
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	}))
	defer srv.Close()

	req, _ := http.NewRequest("GET", srv.URL, nil)
	_, err := Do(srv.Client(), req)
	if err == nil {
		t.Fatal("erwartet Fehler bei HTTP 500")
	}
	if errors.Is(err, ErrPermanent) {
		t.Error("HTTP 500 darf nicht als permanent klassifiziert werden (transient)")
	}
}

func TestDoRejectsOversizedBody(t *testing.T) {
	// 3.42: a compromised server must not be able to OOM the agent — a body over
	// MaxResponseBytes is rejected instead of read whole.
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write(make([]byte, MaxResponseBytes+1))
	}))
	defer srv.Close()

	req, _ := http.NewRequest("GET", srv.URL, nil)
	if _, err := Do(srv.Client(), req); err == nil {
		t.Fatal("erwartet Fehler bei uebergrossem Body")
	}
}

func TestDoAcceptsBodyAtCap(t *testing.T) {
	// A body exactly at the cap is still allowed (off-by-one boundary).
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write(make([]byte, MaxResponseBytes))
	}))
	defer srv.Close()

	req, _ := http.NewRequest("GET", srv.URL, nil)
	body, err := Do(srv.Client(), req)
	if err != nil {
		t.Fatalf("Body genau am Limit sollte erlaubt sein: %v", err)
	}
	if int64(len(body)) != MaxResponseBytes {
		t.Fatalf("len(body) = %d, erwartet %d", len(body), MaxResponseBytes)
	}
}

func TestClientDoesNotFollowRedirects(t *testing.T) {
	// 3.43: Go keeps custom headers (X-API-Key, X-Provision-Token) on a cross-host
	// redirect, so the agent client must not follow one — a 3xx is a final response.
	hitTarget := false
	target := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hitTarget = true
		w.WriteHeader(http.StatusOK)
	}))
	defer target.Close()

	src := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, target.URL, http.StatusFound) // 302 to another host
	}))
	defer src.Close()

	client, err := New("", false, 5*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	req, _ := http.NewRequest("GET", src.URL, nil)
	req.Header.Set("X-API-Key", "secret")
	if _, err := Do(client, req); err == nil {
		t.Fatal("erwartet Fehler: 3xx darf nicht verfolgt werden")
	}
	if hitTarget {
		t.Fatal("Client folgte dem Redirect — Custom-Auth-Header koennte leaken")
	}
}

// writeTestCA writes a minimal self-signed CA cert to a temp file and returns its path (6.99).
func writeTestCA(t *testing.T) string {
	t.Helper()
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	tmpl := &x509.Certificate{
		SerialNumber:          big.NewInt(1),
		Subject:               pkix.Name{CommonName: "test-ca"},
		NotBefore:             time.Now().Add(-time.Hour),
		NotAfter:              time.Now().Add(time.Hour),
		IsCA:                  true,
		KeyUsage:              x509.KeyUsageCertSign,
		BasicConstraintsValid: true,
	}
	der, err := x509.CreateCertificate(rand.Reader, tmpl, tmpl, &key.PublicKey, key)
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(t.TempDir(), "ca.pem")
	pemBytes := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der})
	if err := os.WriteFile(path, pemBytes, 0o600); err != nil {
		t.Fatal(err)
	}
	return path
}

func tlsConfigOf(t *testing.T, c *http.Client) *tls.Config {
	t.Helper()
	tr, ok := c.Transport.(*http.Transport)
	if !ok {
		t.Fatalf("transport is not *http.Transport: %T", c.Transport)
	}
	return tr.TLSClientConfig
}

func TestNewInsecureSkipsVerifyAndPinsTLS12(t *testing.T) {
	client, err := New("", true, time.Second)
	if err != nil {
		t.Fatal(err)
	}
	cfg := tlsConfigOf(t, client)
	if !cfg.InsecureSkipVerify {
		t.Error("insecure=true must set InsecureSkipVerify")
	}
	if cfg.MinVersion != tls.VersionTLS12 {
		t.Errorf("MinVersion = %#x, want TLS1.2", cfg.MinVersion)
	}
}

func TestNewPinsCARootsAndKeepsVerifyOn(t *testing.T) {
	// ADR 0001 D2: a pinned CA goes into RootCAs (system roots are NOT added) and verification stays on.
	client, err := New(writeTestCA(t), false, time.Second)
	if err != nil {
		t.Fatal(err)
	}
	cfg := tlsConfigOf(t, client)
	if cfg.RootCAs == nil {
		t.Error("RootCAs must be the pinned pool, not nil (nil would fall back to system roots)")
	}
	if cfg.InsecureSkipVerify {
		t.Error("a pinned CA must keep verification on")
	}
}

func TestNewRejectsInvalidCAPEM(t *testing.T) {
	path := filepath.Join(t.TempDir(), "bad.pem")
	if err := os.WriteFile(path, []byte("not a pem"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := New(path, false, time.Second); err == nil || !strings.Contains(err.Error(), "ungueltig") {
		t.Errorf("invalid CA PEM must error with 'ungueltig', got %v", err)
	}
}

func TestNewRejectsMissingCAFile(t *testing.T) {
	if _, err := New("/nonexistent/ca.pem", false, time.Second); err == nil {
		t.Error("a missing CA file must error")
	}
}

func TestNewMTLSFailsClosedOnMissingClientCert(t *testing.T) {
	if _, err := NewMTLS("/nope/cert.pem", "/nope/key.pem", writeTestCA(t), time.Second); err == nil {
		t.Error("a missing client cert must error (fail closed, no cert-less client)")
	}
}
