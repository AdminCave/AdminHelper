// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Package httpclient builds the TLS-aware HTTP client shared by the agent
// components (frpc sync, monitor push, provisioning).
package httpclient

import (
	"crypto/tls"
	"crypto/x509"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"time"
)

// ErrPermanent marks an HTTP failure that a retry cannot fix — the agent's
// credentials or identity are the problem (rotated/revoked API key, deleted
// server), not a transient outage. A oneshot run (systemd timer) surfaces it as a
// non-zero exit so OnFailure fires, instead of silently staying green while
// misconfigured (4.80/4.81).
var ErrPermanent = errors.New("permanenter Fehler")

// isPermanentStatus classifies the 4xx codes an agent retry cannot resolve: 401
// (rotated/revoked key), 403 (key lacks the server binding), 404 (server
// deprovisioned). Everything else (5xx, 429, network/timeout) is transient.
func isPermanentStatus(code int) bool {
	return code == http.StatusUnauthorized ||
		code == http.StatusForbidden ||
		code == http.StatusNotFound
}

// noRedirect makes a client return a 3xx as its final response instead of
// following it. Go only strips Authorization/Cookie on a cross-host redirect, so the
// agent's custom auth headers (X-API-Key, X-Provision-Token) would otherwise leak to
// a redirect target chosen by a compromised server. No legitimate agent endpoint
// (activate, config, config-hash, report, enroll, renew) redirects (3.43).
func noRedirect(req *http.Request, via []*http.Request) error {
	return http.ErrUseLastResponse
}

// New creates an HTTP client with optional TLS settings: a pinned CA
// certificate (cacert, PEM file path) or disabled verification (insecure).
func New(cacert string, insecure bool, timeout time.Duration) (*http.Client, error) {
	tlsCfg := &tls.Config{MinVersion: tls.VersionTLS12}
	if insecure {
		tlsCfg.InsecureSkipVerify = true
	} else if cacert != "" {
		pem, err := os.ReadFile(cacert)
		if err != nil {
			return nil, fmt.Errorf("CA-Zertifikat lesen: %w", err)
		}
		pool := x509.NewCertPool()
		if !pool.AppendCertsFromPEM(pem) {
			return nil, fmt.Errorf("CA-Zertifikat ungueltig")
		}
		tlsCfg.RootCAs = pool
	}
	return &http.Client{
		Timeout:       timeout,
		Transport:     &http.Transport{TLSClientConfig: tlsCfg},
		CheckRedirect: noRedirect,
	}, nil
}

// NewMTLS builds a client that presents the given client certificate (cert +
// key PEM files) and trusts ONLY the given CA bundle — system roots are NOT
// added (ADR 0001 D2: validate every leaf against our pinned CA, so even a
// compromised public CA is rejected). Used for all server pushes once the agent
// is enrolled.
func NewMTLS(certPath, keyPath, caPath string, timeout time.Duration) (*http.Client, error) {
	cert, err := tls.LoadX509KeyPair(certPath, keyPath)
	if err != nil {
		return nil, fmt.Errorf("Client-Zertifikat laden: %w", err)
	}
	caPEM, err := os.ReadFile(caPath)
	if err != nil {
		return nil, fmt.Errorf("CA-Zertifikat lesen: %w", err)
	}
	pool := x509.NewCertPool()
	if !pool.AppendCertsFromPEM(caPEM) {
		return nil, fmt.Errorf("CA-Zertifikat ungueltig")
	}
	tlsCfg := &tls.Config{
		Certificates: []tls.Certificate{cert},
		RootCAs:      pool,
		MinVersion:   tls.VersionTLS12,
	}
	return &http.Client{
		Timeout:       timeout,
		Transport:     &http.Transport{TLSClientConfig: tlsCfg},
		CheckRedirect: noRedirect,
	}, nil
}

// MaxResponseBytes caps how much of a response body is read into memory, so a
// compromised server (or a MITM under persisted INSECURE) cannot OOM the agent with a
// multi-GB response. Legitimate bodies (frpc.toml, JSON, PEM chains) are a few KB to a
// few MB. Exported so hand-rolled reads (provision.callActivate) share the same cap.
const MaxResponseBytes int64 = 10 << 20 // 10 MiB

// Do executes req, reads the full body (capped at MaxResponseBytes), and maps a
// >=300 status to an error (with the body for context). Consolidates the
// request/do/read/status pattern that was hand-rolled across the GET/POST helpers so
// behaviour (size, error text) lives in one place. Callers that need the raw
// *http.Response (e.g. the TLS peer certs for TOFU pinning) keep doing client.Do
// directly.
func Do(client *http.Client, req *http.Request) ([]byte, error) {
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, MaxResponseBytes+1))
	if err != nil {
		return nil, err
	}
	if int64(len(body)) > MaxResponseBytes {
		return nil, fmt.Errorf("Antwort ueberschreitet %d Bytes", MaxResponseBytes)
	}
	if resp.StatusCode >= 300 {
		if isPermanentStatus(resp.StatusCode) {
			return nil, fmt.Errorf("%w: HTTP %d: %s", ErrPermanent, resp.StatusCode, body)
		}
		return nil, fmt.Errorf("HTTP %d: %s", resp.StatusCode, body)
	}
	return body, nil
}
