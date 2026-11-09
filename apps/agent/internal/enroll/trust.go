// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package enroll

import (
	"context"
	"crypto/sha256"
	"crypto/x509"
	"encoding/hex"
	"encoding/json"
	"encoding/pem"
	"errors"
	"fmt"
	"io"
	"mime"
	"net/http"
	"os"
	"regexp"
	"strings"
	"time"

	"adminhelper-agent/internal/httpclient"
)

// maxTrustAnswer bounds what FetchTrustGeneration reads: the answer itself,
// {"generation":"<64 hex>"}, is 81 bytes.
const maxTrustAnswer = 4 << 10

var generationPattern = regexp.MustCompile(`^[0-9a-f]{64}$`)

// TrustGeneration is the trust generation of a PEM bundle: SHA-256 over the DER bytes of
// its certificates in their order, as hex. Other PEM blocks and text around them do not
// count. The ca-issuer computes the same over the `chain` it hands out, which Store keeps
// as ca.crt (R-1054).
func TrustGeneration(bundle []byte) (string, error) {
	sum := sha256.New()
	certs := 0
	for rest := bundle; ; {
		var block *pem.Block
		if block, rest = pem.Decode(rest); block == nil {
			break
		}
		if block.Type != "CERTIFICATE" {
			continue
		}
		cert, err := x509.ParseCertificate(block.Bytes)
		if err != nil {
			return "", fmt.Errorf("certificate %d of the trust bundle: %w", certs+1, err)
		}
		sum.Write(cert.Raw)
		certs++
	}
	if certs == 0 {
		return "", errors.New("the trust bundle holds no certificate")
	}
	return hex.EncodeToString(sum.Sum(nil)), nil
}

// heldTrustGeneration is the trust generation of the ca.crt in dir.
func heldTrustGeneration(dir string) (string, error) {
	bundle, err := os.ReadFile(CAPath(dir))
	if err != nil {
		return "", err
	}
	return TrustGeneration(bundle)
}

// FetchTrustGeneration asks <baseURL>/ca/trust over mTLS with the identity in dir for the
// trust generation of its scope. "" without an error means the server does not know the
// route: a 404, or a 200 that is no JSON, because behind a gateway without the location
// the server answers every unknown path outside its API with the web UI.
func FetchTrustGeneration(ctx context.Context, dir, baseURL string, timeout time.Duration) (string, error) {
	client, err := httpclient.NewMTLS(CertPath(dir), KeyPath(dir), CAPath(dir), timeout)
	if err != nil {
		return "", err
	}
	endpoint := strings.TrimRight(baseURL, "/") + "/ca/trust"
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, endpoint, nil)
	if err != nil {
		return "", err
	}
	resp, err := client.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, maxTrustAnswer+1))
	if err != nil {
		return "", err
	}
	if resp.StatusCode == http.StatusNotFound {
		return "", nil
	}
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("HTTP %d: %s", resp.StatusCode, body)
	}
	if mediaType, _, _ := mime.ParseMediaType(resp.Header.Get("Content-Type")); mediaType != "application/json" {
		return "", nil
	}
	if len(body) > maxTrustAnswer {
		return "", fmt.Errorf("the answer exceeds %d bytes", maxTrustAnswer)
	}
	var answer struct {
		Generation string `json:"generation"`
	}
	if err := json.Unmarshal(body, &answer); err != nil {
		return "", fmt.Errorf("parse the answer: %w", err)
	}
	if !generationPattern.MatchString(answer.Generation) {
		return "", fmt.Errorf("the answer names no trust generation: %q", answer.Generation)
	}
	return answer.Generation, nil
}

// trustFunc is the seam MaybeRenew uses to ask for the trust generation, so tests can
// drive the decision without a live issuer.
var trustFunc = FetchTrustGeneration
