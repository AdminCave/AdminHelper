// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package enroll

import (
	"crypto/x509"
	"encoding/pem"
	"fmt"
	"os"
	"strings"
	"time"

	"adminhelper-agent/internal/httpclient"
)

// RenewalFraction renews once the leaf is half through its lifetime (ADR 0001
// §3.3: ~50 % + overlap, so a briefly unreachable issuer never locks the agent
// out — the current cert is still valid for the remaining half).
const RenewalFraction = 0.5

// RenewRequest is the /renew body (CSR only; identity comes from the presented
// client cert, which the gateway verifies and forwards).
type RenewRequest struct {
	CSR string `json:"csr"`
}

// NeedsRenewal reports whether the leaf in certPEM is past `fraction` of its
// lifetime.
func NeedsRenewal(certPEM []byte, fraction float64) (bool, error) {
	block, _ := pem.Decode(certPEM)
	if block == nil {
		return false, fmt.Errorf("kein Zertifikat-PEM")
	}
	cert, err := x509.ParseCertificate(block.Bytes)
	if err != nil {
		return false, fmt.Errorf("Zertifikat parsen: %w", err)
	}
	total := cert.NotAfter.Sub(cert.NotBefore)
	if total <= 0 {
		return true, nil // malformed / already expired -> renew
	}
	return time.Since(cert.NotBefore) >= time.Duration(float64(total)*fraction), nil
}

// leafExpired reports whether the leaf in certPEM is already past NotAfter, returning
// the expiry time for a clear operator message. An expired leaf can never complete the
// mTLS handshake, and under enforcement there is no fallback — so the agent must be
// re-provisioned rather than hang on generic handshake errors (4.8).
func leafExpired(certPEM []byte) (bool, time.Time, error) {
	block, _ := pem.Decode(certPEM)
	if block == nil {
		return false, time.Time{}, fmt.Errorf("kein Zertifikat-PEM")
	}
	cert, err := x509.ParseCertificate(block.Bytes)
	if err != nil {
		return false, time.Time{}, fmt.Errorf("Zertifikat parsen: %w", err)
	}
	return time.Now().After(cert.NotAfter), cert.NotAfter, nil
}

// Renew submits a fresh CSR to <baseURL>/ca/renew using the CURRENT identity for
// mTLS (the issuer derives CN + scope from that presented cert, not the CSR) and
// atomically swaps the stored identity to the new key + cert on success.
func Renew(dir, baseURL string, timeout time.Duration) error {
	client, err := httpclient.NewMTLS(CertPath(dir), KeyPath(dir), CAPath(dir), timeout)
	if err != nil {
		return err
	}
	newKey, err := GenerateKey()
	if err != nil {
		return err
	}
	// CN is cosmetic here — the issuer re-uses the presented cert's identity.
	csr, err := BuildCSR(newKey, "renew")
	if err != nil {
		return err
	}
	endpoint := strings.TrimRight(baseURL, "/") + "/ca/renew"
	resp, err := Submit(client, endpoint, RenewRequest{CSR: string(csr)})
	if err != nil {
		return err
	}
	return Store(dir, newKey, resp)
}

// MaybeRenew renews the enrolled identity if it is due. Returns whether a
// renewal happened. A no-op when the agent is not enrolled.
func MaybeRenew(dir, baseURL string, timeout time.Duration) (bool, error) {
	if !Provisioned(dir) {
		return false, nil
	}
	certPEM, err := os.ReadFile(CertPath(dir))
	if err != nil {
		return false, err
	}
	due, err := NeedsRenewal(certPEM, RenewalFraction)
	if err != nil || !due {
		return false, err
	}
	if err := renewFunc(dir, baseURL, timeout); err != nil {
		return false, err
	}
	return true, nil
}

// renewFunc is the seam MaybeRenew uses for the network renewal, so tests can drive the
// orchestration (provisioned? / due?) without a live enroll server.
var renewFunc = Renew
