// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package enroll

import (
	"bytes"
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/pem"
	"log"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

// The vector of apps/ca-issuer/tests/test_trust_generation.py, word for word: an
// intermediate, then the root that signed it, and their generation. An agent that hashed
// differently from the issuer would renew in every run (R-1054).
const vectorPEM = `-----BEGIN CERTIFICATE-----
MIIBWzCCAQGgAwIBAgIBAjAKBggqhkjOPQQDAjAnMSUwIwYDVQQDDBxUcnVzdCBH
ZW5lcmF0aW9uIFZlY3RvciBSb290MB4XDTI2MDEwMTAwMDAwMFoXDTM2MDEwMTAw
MDAwMFowLzEtMCsGA1UEAwwkVHJ1c3QgR2VuZXJhdGlvbiBWZWN0b3IgSW50ZXJt
ZWRpYXRlMFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAENlpWuP/Az/ZpCk4QzhC/
oanl8a5JQqNqiu4RuDGYA7LvXSImYisiXPSf8ZrxCMhxi/IGSdKm0+MTpc3ayqcJ
waMWMBQwEgYDVR0TAQH/BAgwBgEB/wIBADAKBggqhkjOPQQDAgNIADBFAiEAukbS
+Wub4BgO39JMC2y9J2e+4NqLTmKUmIcjoJLOEmYCIB1ZoZXCZLjd9XLnClmiFqjU
3TN40JGcBWyry5BynfNd
-----END CERTIFICATE-----
-----BEGIN CERTIFICATE-----
MIIBUzCB+aADAgECAgEBMAoGCCqGSM49BAMCMCcxJTAjBgNVBAMMHFRydXN0IEdl
bmVyYXRpb24gVmVjdG9yIFJvb3QwHhcNMjYwMTAxMDAwMDAwWhcNMzYwMTAxMDAw
MDAwWjAnMSUwIwYDVQQDDBxUcnVzdCBHZW5lcmF0aW9uIFZlY3RvciBSb290MFkw
EwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAESKtAajl1thCHlE0v5zSOXeAdmO6VXsrV
8SbexteJY1W85otFaj/hQWZ38U8Joetfv3f8+rTjRtFZdgPblbFmCqMWMBQwEgYD
VR0TAQH/BAgwBgEB/wIBATAKBggqhkjOPQQDAgNJADBGAiEAh2XmSsMTWV+hnvvl
IIs7rSJKt2ktd5KRjwSgjuwT8JMCIQDeuD64qoEs0BA6QdgH2gzpsVZb6iZHVZAx
s1nQfUzhBA==
-----END CERTIFICATE-----
`

const vectorGeneration = "139a62a94601003257d9e50a799f24575ed90c88d9e7e3802f4fe8a7098da902"

// vectorBlocks are the two certificate blocks of vectorPEM, each with its line end.
func vectorBlocks(t *testing.T) (intermediate, root string) {
	t.Helper()
	end := "-----END CERTIFICATE-----\n"
	i := strings.Index(vectorPEM, end) + len(end)
	return vectorPEM[:i], vectorPEM[i:]
}

func TestTrustGenerationMatchesTheIssuerVector(t *testing.T) {
	got, err := TrustGeneration([]byte(vectorPEM))
	if err != nil || got != vectorGeneration {
		t.Fatalf("TrustGeneration(vector) = (%q, %v), want (%q, nil)", got, err, vectorGeneration)
	}
}

// Only the certificates count, as for pki.trust_generation: line ends, text around them
// and other PEM blocks leave the generation as it is.
func TestTrustGenerationReadsOnlyTheCertificates(t *testing.T) {
	intermediate, root := vectorBlocks(t)
	key := "-----BEGIN EC PRIVATE KEY-----\nMHcCAQEEIA==\n-----END EC PRIVATE KEY-----\n"
	for name, bundle := range map[string]string{
		"CRLF line ends":          strings.ReplaceAll(vectorPEM, "\n", "\r\n"),
		"text and blank lines":    "issued chain\n\n" + intermediate + "\n" + root + "\nend\n",
		"a key block between":     intermediate + key + root,
		"no line end at the end":  strings.TrimSuffix(vectorPEM, "\n"),
		"a key block at the head": key + vectorPEM,
	} {
		t.Run(name, func(t *testing.T) {
			got, err := TrustGeneration([]byte(bundle))
			if err != nil || got != vectorGeneration {
				t.Fatalf("TrustGeneration = (%q, %v), want (%q, nil)", got, err, vectorGeneration)
			}
		})
	}
}

// The order is part of the generation: the issuer hashes `chain` as it hands it out.
func TestTrustGenerationKeepsTheOrder(t *testing.T) {
	intermediate, root := vectorBlocks(t)
	got, err := TrustGeneration([]byte(root + intermediate))
	if err != nil {
		t.Fatalf("TrustGeneration(root, intermediate): %v", err)
	}
	if got == vectorGeneration {
		t.Fatal("the swapped chain has the vector's generation, want another")
	}
	only, err := TrustGeneration([]byte(intermediate))
	if err != nil || only == vectorGeneration || only == got {
		t.Fatalf("TrustGeneration(intermediate) = (%q, %v), want a third generation", only, err)
	}
}

func TestTrustGenerationRejectsABundleWithoutCertificates(t *testing.T) {
	garbled := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: []byte("no certificate")})
	for name, bundle := range map[string]string{
		"empty":             "",
		"text":              "not a bundle",
		"only a key":        "-----BEGIN EC PRIVATE KEY-----\nMHcCAQEEIA==\n-----END EC PRIVATE KEY-----\n",
		"a garbled block":   string(garbled),
		"garbled after one": vectorPEM + string(garbled),
	} {
		t.Run(name, func(t *testing.T) {
			if got, err := TrustGeneration([]byte(bundle)); err == nil {
				t.Fatalf("TrustGeneration = %q, want an error", got)
			}
		})
	}
}

// trustServer serves handler over mTLS the way the gateway does: it demands the agent's
// client certificate and presents a leaf under the access intermediate. It returns the
// agent's identity directory and the server's URL.
func trustServer(t *testing.T, handler http.HandlerFunc) (dir, url string) {
	t.Helper()
	dir = t.TempDir()
	now := time.Now()
	certPEM, keyPEM := selfSigned(t, "agent", now.Add(-time.Hour), now.Add(time.Hour))
	mustWrite(t, CertPath(dir), certPEM)
	mustWrite(t, KeyPath(dir), keyPEM)
	clients := x509.NewCertPool()
	if !clients.AppendCertsFromPEM(certPEM) {
		t.Fatal("agent certificate does not load as a client CA")
	}
	gw := gatewayServerCert(t)
	mustWrite(t, CAPath(dir), gw.caPEM)
	srv := httptest.NewUnstartedServer(handler)
	srv.TLS = &tls.Config{
		ClientAuth: tls.RequireAndVerifyClientCert, ClientCAs: clients, Certificates: []tls.Certificate{gw.cert},
	}
	srv.StartTLS()
	t.Cleanup(srv.Close)
	return dir, srv.URL
}

func answer(status int, contentType, body string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if contentType != "" {
			w.Header().Set("Content-Type", contentType)
		}
		w.WriteHeader(status)
		_, _ = w.Write([]byte(body))
	}
}

func TestTrustFetchReadsTheGenerationOverMTLS(t *testing.T) {
	var asked atomic.Int32
	dir, url := trustServer(t, func(w http.ResponseWriter, r *http.Request) {
		asked.Add(1)
		if r.Method != http.MethodGet || r.URL.Path != "/ca/trust" {
			t.Errorf("request = %s %s, want GET /ca/trust", r.Method, r.URL.Path)
		}
		if len(r.TLS.PeerCertificates) == 0 {
			t.Error("the server saw no client certificate")
		}
		answer(http.StatusOK, "application/json", `{"generation":"`+vectorGeneration+`"}`)(w, r)
	})

	got, err := FetchTrustGeneration(context.Background(), dir, url+"/", 5*time.Second)
	if err != nil || got != vectorGeneration {
		t.Fatalf("FetchTrustGeneration = (%q, %v), want (%q, nil)", got, err, vectorGeneration)
	}
	if n := asked.Load(); n != 1 {
		t.Fatalf("the server was asked %d times, want 1", n)
	}
}

// A server without the route: an old gateway passes /ca/trust on to the server, which
// answers an unknown path with the web UI, or with a 404 when it has none.
func TestTrustFetchTreatsAServerWithoutTheRouteAsUnknown(t *testing.T) {
	for name, handler := range map[string]http.HandlerFunc{
		"404":                answer(http.StatusNotFound, "application/json", `{"detail":"Not Found"}`),
		"the web UI":         answer(http.StatusOK, "text/html; charset=utf-8", "<!doctype html><html></html>"),
		"JSON as plain text": answer(http.StatusOK, "text/plain", `{"generation":"`+vectorGeneration+`"}`),
		"a large web UI 404": answer(http.StatusNotFound, "text/html", strings.Repeat("x", 3*maxTrustAnswer)),
	} {
		t.Run(name, func(t *testing.T) {
			dir, url := trustServer(t, handler)
			got, err := FetchTrustGeneration(context.Background(), dir, url, 5*time.Second)
			if err != nil || got != "" {
				t.Fatalf("FetchTrustGeneration = (%q, %v), want (\"\", nil)", got, err)
			}
		})
	}
}

func TestTrustFetchReportsEveryOtherAnswer(t *testing.T) {
	json := "application/json"
	for name, c := range map[string]struct {
		handler http.HandlerFunc
		want    string
	}{
		"429":                {answer(http.StatusTooManyRequests, "text/html", "slow down"), "HTTP 429: slow down"},
		"403":                {answer(http.StatusForbidden, json, `{"detail":"no"}`), "HTTP 403"},
		"502":                {answer(http.StatusBadGateway, "text/html", "bad gateway"), "HTTP 502"},
		"a redirect":         {answer(http.StatusFound, "", ""), "HTTP 302"},
		"no JSON":            {answer(http.StatusOK, json, "{"), "parse the answer"},
		"no generation":      {answer(http.StatusOK, json, `{}`), "names no trust generation"},
		"upper-case hex":     {answer(http.StatusOK, json, `{"generation":"`+strings.ToUpper(vectorGeneration)+`"}`), "names no trust generation"},
		"a short generation": {answer(http.StatusOK, json, `{"generation":"`+vectorGeneration[:63]+`"}`), "names no trust generation"},
		"too long": {answer(http.StatusOK, json,
			`{"generation":"`+vectorGeneration+`","pad":"`+strings.Repeat("x", maxTrustAnswer)+`"}`), "exceeds"},
	} {
		t.Run(name, func(t *testing.T) {
			dir, url := trustServer(t, c.handler)
			got, err := FetchTrustGeneration(context.Background(), dir, url, 5*time.Second)
			if err == nil || got != "" || !strings.Contains(err.Error(), c.want) {
				t.Fatalf("FetchTrustGeneration = (%q, %v), want (\"\", an error with %q)", got, err, c.want)
			}
		})
	}
}

func TestTrustFetchReportsAnUnreachableServer(t *testing.T) {
	srv := httptest.NewServer(http.NotFoundHandler())
	dir, _ := trustServer(t, answer(http.StatusNotFound, "", ""))
	url := srv.URL
	srv.Close()

	if got, err := FetchTrustGeneration(context.Background(), dir, url, 5*time.Second); err == nil || got != "" {
		t.Fatalf("FetchTrustGeneration against a closed port = (%q, %v), want an error", got, err)
	}
}

// captureLog sends the logs of one test into the returned buffer.
func captureLog(t *testing.T) *bytes.Buffer {
	t.Helper()
	var buf bytes.Buffer
	prev, prevOut, prevFlags := slog.Default(), log.Writer(), log.Flags()
	slog.SetDefault(slog.New(slog.NewTextHandler(&buf, nil)))
	// SetDefault also redirects the log package, which restoring the slog default does not undo.
	t.Cleanup(func() { slog.SetDefault(prev); log.SetOutput(prevOut); log.SetFlags(prevFlags) })
	return &buf
}
