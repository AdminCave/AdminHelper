// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Package httpclient builds the TLS-aware HTTP client shared by the agent
// components (frpc sync, monitor push, provisioning).
package httpclient

import (
	"crypto/tls"
	"crypto/x509"
	"fmt"
	"io"
	"net/http"
	"os"
	"time"
)

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
		Timeout:   timeout,
		Transport: &http.Transport{TLSClientConfig: tlsCfg},
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
		Timeout:   timeout,
		Transport: &http.Transport{TLSClientConfig: tlsCfg},
	}, nil
}

// Do executes req, reads the full body, and maps a >=300 status to an error
// (with the body for context). Consolidates the request/do/read/status pattern
// that was hand-rolled across the GET/POST helpers so behaviour (size, error
// text) lives in one place. Callers that need the raw *http.Response (e.g. the
// TLS peer certs for TOFU pinning) keep doing client.Do directly.
func Do(client *http.Client, req *http.Request) ([]byte, error) {
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}
	if resp.StatusCode >= 300 {
		return nil, fmt.Errorf("HTTP %d: %s", resp.StatusCode, body)
	}
	return body, nil
}
