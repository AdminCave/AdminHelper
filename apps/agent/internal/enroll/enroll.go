// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Package enroll implements the agent side of the PKI enrollment (ADR 0001 §3.3).
//
// On provisioning the agent generates an ECDSA key on-device (the private key
// never leaves the host), builds a CSR, and redeems the one-time enrollment
// token at the gateway's certless enroll plane. The ca-issuer signs a tunnel-
// scoped client leaf; the agent persists key (0600) + cert + the pinned trust
// bundle (intermediate + root) and from then on presents the client cert on all
// server pushes. Renewal (without a token) is in renew.go.
package enroll

import (
	"bytes"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/json"
	"encoding/pem"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
)

// File layout inside the agent identity directory.
const (
	KeyFileName  = "agent.key" // EC private key, 0600 (never leaves the host)
	CertFileName = "agent.crt" // fullchain leaf + intermediate (presented)
	CAFileName   = "ca.crt"    // pinned trust bundle intermediate + root
)

// KeyPath, CertPath and CAPath resolve the identity files inside dir.
func KeyPath(dir string) string  { return filepath.Join(dir, KeyFileName) }
func CertPath(dir string) string { return filepath.Join(dir, CertFileName) }
func CAPath(dir string) string   { return filepath.Join(dir, CAFileName) }

// EnrollRequest is the body the ca-issuer /enroll expects (token + PEM CSR).
type EnrollRequest struct {
	Token string `json:"token"`
	CSR   string `json:"csr"`
}

// IssueResponse is what /enroll and /renew return.
//
//	cert      the leaf alone
//	fullchain leaf + signing intermediate (what we present to the gateway)
//	chain     intermediate + root (what we pin and verify the gateway against)
type IssueResponse struct {
	Cert      string `json:"cert"`
	Fullchain string `json:"fullchain"`
	Chain     string `json:"chain"`
}

// GenerateKey returns a fresh ECDSA P-256 key (D10: fits the Windows keyring
// limit, modern, ideal for short-lived certs).
func GenerateKey() (*ecdsa.PrivateKey, error) {
	return ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
}

// BuildCSR builds a PEM CSR for the given CN. The issuer dictates the real
// identity (CN + scope) from the server-minted grant, so the CSR subject is only
// cosmetic — a client cannot widen its identity through the CSR.
func BuildCSR(key *ecdsa.PrivateKey, cn string) ([]byte, error) {
	der, err := x509.CreateCertificateRequest(
		rand.Reader, &x509.CertificateRequest{Subject: pkix.Name{CommonName: cn}}, key,
	)
	if err != nil {
		return nil, fmt.Errorf("CSR erstellen: %w", err)
	}
	return pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE REQUEST", Bytes: der}), nil
}

// encodeKeyPEM serializes an EC key to PKCS#8 PEM.
func encodeKeyPEM(key *ecdsa.PrivateKey) ([]byte, error) {
	der, err := x509.MarshalPKCS8PrivateKey(key)
	if err != nil {
		return nil, fmt.Errorf("Key serialisieren: %w", err)
	}
	return pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: der}), nil
}

// Submit POSTs a JSON body (an EnrollRequest, or a {csr} renewal) to the issuer
// endpoint via the given client and decodes the issued materials. The client
// carries the TLS trust: a TOFU-pinned gateway cert on enroll, the persisted
// pinned CA on renew.
func Submit(client *http.Client, endpoint string, body any) (*IssueResponse, error) {
	payload, err := json.Marshal(body)
	if err != nil {
		return nil, err
	}
	req, err := http.NewRequest("POST", endpoint, bytes.NewReader(payload))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("Verbindung zum Issuer: %w", err)
	}
	defer resp.Body.Close()

	data, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}
	if resp.StatusCode >= 300 {
		return nil, fmt.Errorf("Issuer-Aufruf fehlgeschlagen (HTTP %d): %s", resp.StatusCode, string(data))
	}

	var out IssueResponse
	if err := json.Unmarshal(data, &out); err != nil {
		return nil, fmt.Errorf("Issuer-Antwort parsen: %w", err)
	}
	if out.Fullchain == "" || out.Chain == "" {
		return nil, fmt.Errorf("unvollstaendige Issuer-Antwort (fullchain/chain fehlt)")
	}
	return &out, nil
}

// Store persists the issued identity under dir: key 0600, cert (the fullchain we
// present) and the pinned trust bundle. The key is written first, so a failure
// cannot leave a cert without its key.
func Store(dir string, key *ecdsa.PrivateKey, resp *IssueResponse) error {
	if err := os.MkdirAll(dir, 0700); err != nil {
		return fmt.Errorf("Identity-Verzeichnis anlegen: %w", err)
	}
	keyPEM, err := encodeKeyPEM(key)
	if err != nil {
		return err
	}
	if err := writeFile(KeyPath(dir), keyPEM, 0600); err != nil {
		return err
	}
	if err := writeFile(CertPath(dir), []byte(resp.Fullchain), 0644); err != nil {
		return err
	}
	return writeFile(CAPath(dir), []byte(resp.Chain), 0644)
}

// Provisioned reports whether an enrolled identity (cert + key) exists in dir.
func Provisioned(dir string) bool {
	return fileExists(CertPath(dir)) && fileExists(KeyPath(dir))
}

func writeFile(path string, data []byte, perm os.FileMode) error {
	if err := os.WriteFile(path, data, perm); err != nil {
		return fmt.Errorf("%s schreiben: %w", filepath.Base(path), err)
	}
	// WriteFile keeps an existing file's mode, so re-assert it on overwrite.
	return os.Chmod(path, perm)
}

func fileExists(path string) bool {
	info, err := os.Stat(path)
	return err == nil && !info.IsDir()
}
