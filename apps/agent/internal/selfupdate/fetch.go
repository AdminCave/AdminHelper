// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package selfupdate

import (
	"bufio"
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

// Files of a Windows release set, exactly as SHA256SUMS names them.
const (
	VersionFile = "VERSION"
	AgentFile   = "adminhelper-agent.exe"
	FrpcFile    = "frpc.exe"
)

const (
	repoPort     = "8445"
	maxSmallFile = 4 << 10
	maxBinary    = 256 << 20
)

// ErrUpToDate means the repo offers no release newer than the running one
// (or only the version that failed before).
var ErrUpToDate = errors.New("selfupdate: no newer release")

// Options for Fetch.
type Options struct {
	RepoURL   string // https://<host>:8445/windows/
	Client    *http.Client
	PublicKey string
	Current   string // running version, "v1.2.3" or "1.2.3"
	Skip      string // version that failed its health check before
	StageDir  string // receives the verified AgentFile and FrpcFile
}

// RepoURL derives the repo plane's Windows directory from the server URL.
func RepoURL(serverBase string) (string, error) {
	u, err := url.Parse(serverBase)
	if err != nil || u.Hostname() == "" {
		return "", fmt.Errorf("selfupdate: invalid server URL")
	}
	return (&url.URL{Scheme: "https", Host: net.JoinHostPort(u.Hostname(), repoPort), Path: "/windows/"}).String(), nil
}

// ParseVersion accepts exactly X.Y.Z with an optional leading "v"; anything
// else (dev, git-describe suffixes) is not a release.
func ParseVersion(s string) ([3]int, bool) {
	var v [3]int
	parts := strings.Split(strings.TrimPrefix(strings.TrimSpace(s), "v"), ".")
	if len(parts) != 3 {
		return v, false
	}
	for i, p := range parts {
		if p == "" || strings.Trim(p, "0123456789") != "" || (len(p) > 1 && p[0] == '0') {
			return v, false
		}
		n, err := strconv.Atoi(p)
		if err != nil {
			return v, false
		}
		v[i] = n
	}
	return v, true
}

// Newer reports whether candidate is a release strictly greater than current.
// A running non-release build never updates itself.
func Newer(candidate, current string) bool {
	c, ok1 := ParseVersion(candidate)
	r, ok2 := ParseVersion(current)
	if !ok1 || !ok2 {
		return false
	}
	for i := range c {
		if c[i] != r[i] {
			return c[i] > r[i]
		}
	}
	return false
}

// sameVersion reports whether a and b are the same release, "v1.2.3" and "1.2.3" alike.
func sameVersion(a, b string) bool {
	x, ok1 := ParseVersion(a)
	y, ok2 := ParseVersion(b)
	return ok1 && ok2 && x == y
}

// parseSums reads sha256sum output and requires exactly the three release files.
func parseSums(data []byte) (map[string]string, error) {
	sums := map[string]string{}
	sc := bufio.NewScanner(bytes.NewReader(data))
	for sc.Scan() {
		line := strings.TrimRight(sc.Text(), "\r")
		if line == "" {
			continue
		}
		hash, name, ok := strings.Cut(line, "  ")
		name = strings.TrimPrefix(name, "*")
		if _, err := hex.DecodeString(hash); !ok || err != nil || len(hash) != 64 {
			return nil, fmt.Errorf("selfupdate: malformed SHA256SUMS line")
		}
		if _, dup := sums[name]; dup {
			return nil, fmt.Errorf("selfupdate: duplicate entry %q in SHA256SUMS", name)
		}
		sums[name] = strings.ToLower(hash)
	}
	for _, want := range []string{VersionFile, AgentFile, FrpcFile} {
		if _, ok := sums[want]; !ok {
			return nil, fmt.Errorf("selfupdate: SHA256SUMS lacks %s", want)
		}
	}
	if len(sums) != 3 {
		return nil, fmt.Errorf("selfupdate: SHA256SUMS lists unexpected files")
	}
	return sums, nil
}

// TrustedComment is what the release signs into SHA256SUMS.minisig; binding
// the version stops a signed older set from being replayed under a new VERSION.
func TrustedComment(version string) string {
	return "adminhelper-agent windows v" + strings.TrimPrefix(version, "v")
}

// Fetch checks the repo for a newer signed release and, if there is one,
// downloads the agent and frpc into StageDir and verifies them. It returns
// the staged version or ErrUpToDate.
func Fetch(ctx context.Context, o Options) (string, error) {
	sums, err := get(ctx, o, "SHA256SUMS", maxSmallFile)
	if err != nil {
		return "", err
	}
	sig, err := get(ctx, o, "SHA256SUMS.minisig", maxSmallFile)
	if err != nil {
		return "", err
	}
	trusted, err := Verify(o.PublicKey, sums, sig)
	if err != nil {
		return "", err
	}
	hashes, err := parseSums(sums)
	if err != nil {
		return "", err
	}
	verRaw, err := get(ctx, o, VersionFile, 64)
	if err != nil {
		return "", err
	}
	if err := checkHash(verRaw, hashes[VersionFile], VersionFile); err != nil {
		return "", err
	}
	version := strings.TrimSpace(string(verRaw))
	if _, ok := ParseVersion(version); !ok {
		return "", fmt.Errorf("selfupdate: VERSION is not a release")
	}
	if trusted != TrustedComment(version) {
		return "", fmt.Errorf("selfupdate: signature does not belong to version %s", version)
	}
	if !Newer(version, o.Current) || sameVersion(version, o.Skip) {
		return "", ErrUpToDate
	}
	// The stage only ever holds one complete, verified set.
	if err := os.RemoveAll(o.StageDir); err != nil {
		return "", err
	}
	if err := os.MkdirAll(o.StageDir, 0o700); err != nil {
		return "", err
	}
	for _, name := range []string{AgentFile, FrpcFile} {
		if err := download(ctx, o, name, hashes[name]); err != nil {
			os.RemoveAll(o.StageDir)
			return "", err
		}
	}
	return version, nil
}

func checkHash(data []byte, want, name string) error {
	sum := sha256.Sum256(data)
	if hex.EncodeToString(sum[:]) != want {
		return fmt.Errorf("selfupdate: checksum mismatch for %s", name)
	}
	return nil
}

func open(ctx context.Context, o Options, name string) (io.ReadCloser, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, o.RepoURL+name, nil)
	if err != nil {
		return nil, err
	}
	resp, err := o.Client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("selfupdate: fetch %s: %w", name, err)
	}
	if resp.StatusCode != http.StatusOK {
		resp.Body.Close()
		return nil, fmt.Errorf("selfupdate: fetch %s: HTTP %d", name, resp.StatusCode)
	}
	return resp.Body, nil
}

func get(ctx context.Context, o Options, name string, limit int64) ([]byte, error) {
	body, err := open(ctx, o, name)
	if err != nil {
		return nil, err
	}
	defer body.Close()
	data, err := io.ReadAll(io.LimitReader(body, limit+1))
	if err != nil {
		return nil, fmt.Errorf("selfupdate: fetch %s: %w", name, err)
	}
	if int64(len(data)) > limit {
		return nil, fmt.Errorf("selfupdate: %s too large", name)
	}
	return data, nil
}

// download streams name into StageDir, hashing on the way.
func download(ctx context.Context, o Options, name, want string) error {
	body, err := open(ctx, o, name)
	if err != nil {
		return err
	}
	defer body.Close()
	dst := filepath.Join(o.StageDir, name)
	part := dst + ".part"
	f, err := os.OpenFile(part, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0o600)
	if err != nil {
		return err
	}
	h := sha256.New()
	n, err := io.Copy(io.MultiWriter(f, h), io.LimitReader(body, maxBinary+1))
	if cerr := f.Close(); err == nil {
		err = cerr
	}
	if err == nil && n > maxBinary {
		err = fmt.Errorf("selfupdate: %s too large", name)
	}
	if err == nil && hex.EncodeToString(h.Sum(nil)) != want {
		err = fmt.Errorf("selfupdate: checksum mismatch for %s", name)
	}
	if err != nil {
		return err
	}
	return os.Rename(part, dst)
}
