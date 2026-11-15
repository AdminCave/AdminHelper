// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

// The tests that write certificate files: the views read them by a plain absolute Unix path only.

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"errors"
	"fmt"
	"math/big"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// namedCertPEM is a certificate for name valid until notAfter, as PEM, after a private key when withKey.
func namedCertPEM(t *testing.T, name string, notAfter time.Time, withKey bool) []byte {
	t.Helper()
	k, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	tmpl := &x509.Certificate{
		SerialNumber: big.NewInt(9), Subject: pkix.Name{CommonName: name}, DNSNames: []string{name},
		NotBefore: start.Add(-time.Hour), NotAfter: notAfter,
	}
	der, err := x509.CreateCertificate(rand.Reader, tmpl, tmpl, &k.PublicKey, k)
	if err != nil {
		t.Fatal(err)
	}
	var out []byte
	if withKey {
		kd, err := x509.MarshalECPrivateKey(k)
		if err != nil {
			t.Fatal(err)
		}
		out = pem.EncodeToMemory(&pem.Block{Type: "EC PRIVATE KEY", Bytes: kd})
	}
	return append(out, pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der})...)
}

// writeCertFile writes data to name in dir and returns its path.
func writeCertFile(t *testing.T, dir, name string, data []byte) string {
	t.Helper()
	p := filepath.Join(dir, name)
	if err := os.WriteFile(p, data, 0o600); err != nil {
		t.Fatal(err)
	}
	return p
}

func vhostTarget(port int) Target {
	return Target{Kind: kindVhost, Name: "svc.example.org", PortHint: port}
}

func TestWebVhostCertComparesTheFileWithTheServedCertificate(t *testing.T) {
	pki := newPKI(t)
	stubNow(t, start)
	stubRoots(t, pki.roots)
	freshSnapshot(t)
	port, names := tlsServer(t, pki.chain)
	ctx := context.Background()
	dir := t.TempDir()
	served := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: pki.leaf.Raw})
	same := writeCertFile(t, dir, "same.pem", served)
	newer := writeCertFile(t, dir, "newer.pem", namedCertPEM(t, "svc.example.org", start.Add(90*24*time.Hour), true))
	older := writeCertFile(t, dir, "older.pem", namedCertPEM(t, "svc.example.org", start.Add(10*24*time.Hour), false))
	vhost := func(cert string) []Vhost {
		return []Vhost{
			{Server: "nginx", Name: "svc.example.org", Port: uint16(port) + 1, TLS: true, cert: older},
			{Server: "nginx", Name: "svc.example.org", Port: uint16(port), TLS: true, cert: cert},
		}
	}
	cases := []struct {
		name, cert string
		want       map[string]any
	}{
		{"the file it serves", same, map[string]any{"served_days_left": int64(30), "hostname_ok": true, "chain_ok": true,
			"file_days_left": int64(30), "reload_missing": false}},
		{"a renewed file", newer, map[string]any{"served_days_left": int64(30), "hostname_ok": true, "chain_ok": true,
			"file_days_left": int64(90), "reload_missing": true}},
		{"another file that ends sooner", older, map[string]any{"served_days_left": int64(30), "hostname_ok": true,
			"chain_ok": true, "file_days_left": int64(10), "reload_missing": false}},
		{"no file", "", map[string]any{"served_days_left": int64(30), "hostname_ok": true, "chain_ok": true}},
		{"no plain path", dir + "/../same.pem x", map[string]any{"served_days_left": int64(30), "hostname_ok": true,
			"chain_ok": true}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			stubVhostCache(t, time.Now(), vhost(c.cert), nil)
			got, err := webVhostCert(ctx, vhostTarget(port))
			if err != nil || fmt.Sprint(got) != fmt.Sprint(c.want) {
				t.Errorf("web_vhost_cert = %v, %v\nwant %v", got, err, c.want)
			}
			if name := <-names; name != "svc.example.org" {
				t.Errorf("the server was asked for %q, want the domain", name)
			}
		})
	}
}

func TestWebVhostCertNeedsAVhostWithTLSOfThisHost(t *testing.T) {
	ctx := context.Background()
	broken := errors.New("nginx -T failed")
	cases := []struct {
		name string
		list []Vhost
		err  error
		want string
	}{
		{"another port", []Vhost{{Name: "svc.example.org", Port: 443, TLS: true}}, nil, "no web server of this host serves"},
		{"another name", []Vhost{{Name: "web.example.org", Port: 8443, TLS: true}}, nil, "no web server of this host serves"},
		{"without TLS", []Vhost{{Name: "svc.example.org", Port: 8443}}, nil, "served without TLS"},
		{"a configuration that cannot be read", nil, broken, "nginx -T failed"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			stubVhostCache(t, time.Now(), c.list, c.err)
			got, err := webVhostCert(ctx, vhostTarget(8443))
			if err == nil || !strings.Contains(err.Error(), c.want) {
				t.Errorf("web_vhost_cert = %v, %v; want an error naming %q", got, err, c.want)
			}
		})
	}
}

func TestTheVhostsAreReadOnceAMinute(t *testing.T) {
	stubVhostCache(t, time.Time{}, nil, nil)
	calls := stubTools(t, answer{out: "nginx: the configuration file /etc/nginx/nginx.conf syntax is ok\n"},
		answer{err: exec.ErrNotFound}, answer{err: exec.ErrNotFound},
		answer{out: "nginx: the configuration file /etc/nginx/nginx.conf syntax is ok\n"},
		answer{err: exec.ErrNotFound}, answer{err: exec.ErrNotFound})
	ctx := context.Background()
	for range 3 {
		if _, err := cachedVhosts(ctx); err != nil {
			t.Fatal(err)
		}
	}
	if len(*calls) != 3 {
		t.Errorf("three reads within a minute ran %d tools, want the 3 of one read", len(*calls))
	}
	vhostCache.Lock()
	vhostCache.at = time.Now().Add(-vhostTTL)
	vhostCache.Unlock()
	if _, err := cachedVhosts(ctx); err != nil || len(*calls) != 6 {
		t.Errorf("a read after a minute = %v, %d tools; want the configuration read again", err, len(*calls))
	}
}
