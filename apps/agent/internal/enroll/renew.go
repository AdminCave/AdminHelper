// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package enroll

import (
	"context"
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
// atomically swaps the stored identity to the new key + cert on success. The
// caller holds LockIdentity, as for Store. ctx ends the request to the issuer;
// the stored identity then stays as it was.
func Renew(ctx context.Context, dir, baseURL string, timeout time.Duration) error {
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
	resp, err := Submit(ctx, client, endpoint, RenewRequest{CSR: string(csr)})
	if err != nil {
		return err
	}
	return Store(dir, newKey, resp)
}

// Renewal is why MaybeRenew renewed the identity, or NoRenewal.
type Renewal int

const (
	NoRenewal Renewal = iota
	// HalfLife: the leaf is past RenewalFraction of its lifetime.
	HalfLife
	// NewTrust: the issuer names another trust generation than that of the held ca.crt,
	// after a rotation of the root or the intermediates (R-1054).
	NewTrust
)

func (r Renewal) String() string {
	switch r {
	case HalfLife:
		return "half of its lifetime has passed"
	case NewTrust:
		return "the issuer has a new trust generation"
	}
	return "not renewed"
}

// MaybeRenew renews the enrolled identity if it is due and returns why, or NoRenewal.
// A no-op when the agent is not enrolled. An identity that is not yet at half of its
// lifetime asks the issuer for its trust generation (trustFunc) and is due when that
// differs from the held ca.crt's; a server without the route leaves it at the half.
//
// It takes LockIdentity only for a due identity: a lock that is not released holds
// up no service cycle with nothing to renew, and one with a due identity gets the
// error of LockIdentity once its wait is over or ctx has ended. The lock is held
// from reading the certificate to the commit in Store (R-0384). A provisioning that
// held the lock before it may have dropped or replaced the identity, and the issuer
// has revoked the line of the old one: so the check runs again under the lock, and
// a fresh certificate, or one stored with the new trust bundle, is not renewed.
func MaybeRenew(ctx context.Context, dir, baseURL string, timeout time.Duration) (Renewal, error) {
	if !Provisioned(dir) {
		return NoRenewal, nil
	}
	reason, err := renewalReason(dir, "")
	if err != nil {
		return NoRenewal, err
	}
	issuerGeneration := ""
	if reason == NoRenewal {
		if issuerGeneration, err = trustFunc(ctx, dir, baseURL, timeout); err != nil {
			return NoRenewal, fmt.Errorf("trust generation: %w", err)
		}
		if reason, err = renewalReason(dir, issuerGeneration); err != nil || reason == NoRenewal {
			return NoRenewal, err
		}
	}
	unlock, err := LockIdentity(ctx, dir)
	if err != nil {
		return NoRenewal, err
	}
	defer unlock()
	RemoveStaleTemps(dir)
	if reason, err = renewalReason(dir, issuerGeneration); err != nil || reason == NoRenewal {
		return NoRenewal, err
	}
	if err := renewFunc(ctx, dir, baseURL, timeout); err != nil {
		return NoRenewal, err
	}
	if reason == NewTrust {
		// Should the agent and the issuer ever compute the generation differently,
		// every run renews again; this names that loop.
		if held, err := heldTrustGeneration(dir); err != nil {
			logger.Warnf("trust generation of the renewed ca.crt: %v", err)
		} else if held != issuerGeneration {
			logger.Warnf("the renewed ca.crt has trust generation %s, the issuer named %s; the next run renews again", held, issuerGeneration)
		}
	}
	return reason, nil
}

// renewalReason tells why the identity in dir is due for renewal, or NoRenewal. A
// non-empty issuerGeneration is compared with the trust generation of the held ca.crt.
func renewalReason(dir, issuerGeneration string) (Renewal, error) {
	if !Provisioned(dir) {
		return NoRenewal, nil
	}
	certPEM, err := os.ReadFile(CertPath(dir))
	if err != nil {
		return NoRenewal, err
	}
	due, err := NeedsRenewal(certPEM, RenewalFraction)
	if err != nil {
		return NoRenewal, err
	}
	if due {
		return HalfLife, nil
	}
	if issuerGeneration == "" {
		return NoRenewal, nil
	}
	held, err := heldTrustGeneration(dir)
	if err != nil {
		return NoRenewal, err
	}
	if held != issuerGeneration {
		return NewTrust, nil
	}
	return NoRenewal, nil
}

// renewFunc is the seam MaybeRenew uses for the network renewal, so tests can drive the
// orchestration (provisioned? / due?) without a live enroll server.
var renewFunc = Renew
