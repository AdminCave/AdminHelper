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
	"net/http"
	"os"
	"path/filepath"

	"adminhelper-agent/internal/httpclient"
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

// Request is the body the ca-issuer /enroll expects (token + PEM CSR).
type Request struct {
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

// Submit POSTs a JSON body (a Request, or a {csr} renewal) to the issuer
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

	data, err := httpclient.Do(client, req)
	if err != nil {
		return nil, fmt.Errorf("Issuer-Aufruf: %w", err)
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

// tmpSuffix marks the staging copies written before the atomic rename.
const tmpSuffix = ".tmp"

// Store persists the issued identity under dir: key 0600, cert (the fullchain we
// present) and the pinned trust bundle. Renewal mints a NEW key, so the write
// must be crash-atomic: writing the key in place and then the cert would, if
// interrupted in between, leave a new key paired with the OLD cert — a mismatch
// that breaks every subsequent mTLS handshake and locks the agent out until it
// is re-provisioned (ADR 0001 §3.3). Instead the new material is fully staged to
// temp files and then renamed into place, so an interrupted renew leaves the
// previous consistent pair untouched.
func Store(dir string, key *ecdsa.PrivateKey, resp *IssueResponse) error {
	if err := os.MkdirAll(dir, 0700); err != nil {
		return fmt.Errorf("Identity-Verzeichnis anlegen: %w", err)
	}
	commit, err := stageIdentity(dir, key, resp)
	if err != nil {
		return err
	}
	return commit()
}

// staged is one identity file: its temp copy, its final path, its mode.
type staged struct {
	tmp   string
	final string
	perm  os.FileMode
}

// stageIdentity writes the new key/cert/CA to fsynced temp files and returns a
// commit closure that atomically renames them into place. Until commit runs the
// live identity files are untouched. The residual window — the two adjacent
// rename(2) calls — is nanoseconds and involves no I/O, versus the original
// window that spanned the network fetch plus the file writes.
func stageIdentity(dir string, key *ecdsa.PrivateKey, resp *IssueResponse) (func() error, error) {
	keyPEM, err := encodeKeyPEM(key)
	if err != nil {
		return nil, err
	}
	items := []staged{
		{KeyPath(dir) + tmpSuffix, KeyPath(dir), 0600},
		{CertPath(dir) + tmpSuffix, CertPath(dir), 0644},
		{CAPath(dir) + tmpSuffix, CAPath(dir), 0644},
	}
	contents := [][]byte{keyPEM, []byte(resp.Fullchain), []byte(resp.Chain)}
	for i, it := range items {
		if err := writeFileSync(it.tmp, contents[i], it.perm); err != nil {
			for _, done := range items[:i+1] { // best-effort cleanup of staged temps
				_ = os.Remove(done.tmp)
			}
			return nil, err
		}
	}
	return func() error {
		for _, it := range items {
			if err := os.Rename(it.tmp, it.final); err != nil {
				return fmt.Errorf("%s aktivieren: %w", filepath.Base(it.final), err)
			}
		}
		return syncDir(dir)
	}, nil
}

// Provisioned reports whether an enrolled identity (cert + key) exists in dir.
func Provisioned(dir string) bool {
	return fileExists(CertPath(dir)) && fileExists(KeyPath(dir))
}

// writeFileSync writes data to path with the given mode and fsyncs it, so the
// bytes are durable before the rename that activates the staged file.
func writeFileSync(path string, data []byte, perm os.FileMode) error {
	f, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, perm)
	if err != nil {
		return fmt.Errorf("%s schreiben: %w", filepath.Base(path), err)
	}
	if _, err := f.Write(data); err != nil {
		f.Close()
		return fmt.Errorf("%s schreiben: %w", filepath.Base(path), err)
	}
	if err := f.Sync(); err != nil {
		f.Close()
		return fmt.Errorf("%s synchronisieren: %w", filepath.Base(path), err)
	}
	// O_CREAT keeps an existing file's mode, so re-assert it on overwrite.
	if err := f.Chmod(perm); err != nil {
		f.Close()
		return fmt.Errorf("%s chmod: %w", filepath.Base(path), err)
	}
	return f.Close()
}

// syncDir fsyncs a directory so the renames within it are durable.
func syncDir(dir string) error {
	d, err := os.Open(dir)
	if err != nil {
		return err
	}
	defer d.Close()
	if err := d.Sync(); err != nil {
		// Some filesystems reject directory fsync; the renames are still atomic.
		return nil
	}
	return nil
}

func fileExists(path string) bool {
	info, err := os.Stat(path)
	return err == nil && !info.IsDir()
}
