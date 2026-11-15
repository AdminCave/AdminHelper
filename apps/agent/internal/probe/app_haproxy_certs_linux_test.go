// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

// The tests of haproxy_certs: it reads certificate files by a plain absolute Unix path only.

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"
)

func TestHAProxyCertsReadsTheCertificatesOfItsBindLines(t *testing.T) {
	stubNow(t, start)
	base, dir := t.TempDir(), t.TempDir()
	day := 24 * time.Hour
	writeCertFile(t, base, "site.pem", namedCertPEM(t, "a.example.org", start.Add(60*day+time.Hour), true))
	writeCertFile(t, dir, "b.pem", namedCertPEM(t, "b.example.org", start.Add(5*day+time.Hour), false))
	writeCertFile(t, dir, "c.pem", namedCertPEM(t, "c.example.org", start.Add(13*day+time.Hour), true))
	// What HAProxy loads beside a certificate of a directory, not as one, and a hidden file: none of
	// them is a certificate, so reading one would fail the view.
	for _, n := range []string{"b.pem.key", "b.pem.issuer", "b.pem.ocsp", "b.pem.sctl", ".c.pem.swp"} {
		writeCertFile(t, dir, n, []byte("no certificate\n"))
	}
	if err := os.Mkdir(filepath.Join(dir, "old"), 0o700); err != nil {
		t.Fatal(err)
	}
	haproxyConfigFile(t, "global\n  crt-base "+base+"\n"+
		"frontend https\n"+
		"  bind :443 ssl crt site.pem crt \""+dir+"\" alpn h2  # crt "+dir+"/b.pem.key\n"+
		"  bind :8443 ssl crt "+base+"/site.pem crt gone.pem\n"+
		"#  bind :9443 ssl crt /etc/haproxy/off.pem\n"+
		"  http-request set-header X-Crt crt\n")

	got, err := haproxyCerts(context.Background(), Target{Kind: kindUnit, Name: "haproxy.service"})
	want := map[string]any{"certs": 3, "min_days_left": int64(5), "expiring_14d": 2}
	if err != nil || fmt.Sprint(got) != fmt.Sprint(want) {
		t.Errorf("haproxy_certs = %v, %v; want %v", got, err, want)
	}
}

func TestHAProxyCertPathsTakesPlainPathsOnly(t *testing.T) {
	cfg := "crt-base /etc/haproxy/certs\n" +
		"bind :443 ssl crt a.pem crt /etc/ssl/b.pem crt 'c.pem' crt /etc/ssl/b.pem\n" +
		"bind :444 ssl crt /etc/ssl/../x.pem\x01 crt $HOME/d.pem crt\n" +
		"bind :445 ssl crt-list /etc/haproxy/list.txt\n"
	got := haproxyCertPaths([]byte(cfg))
	want := []string{"/etc/haproxy/certs/a.pem", "/etc/ssl/b.pem", "/etc/haproxy/certs/c.pem"}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("paths = %q, want %q", got, want)
	}
	if got := haproxyCertPaths([]byte("bind :443 ssl crt a.pem\n")); got != nil {
		t.Errorf("a relative path without crt-base = %q, want none", got)
	}
}

func TestHAProxyCertsWithoutCertificatesOrTooMany(t *testing.T) {
	ctx := context.Background()
	unit := Target{Kind: kindUnit, Name: "haproxy.service"}
	haproxyConfigFile(t, "frontend http\n  bind :80\n")
	got, err := haproxyCerts(ctx, unit)
	if want := map[string]any{"certs": 0, "expiring_14d": 0}; err != nil || !reflect.DeepEqual(got, want) {
		t.Errorf("haproxy_certs without TLS = %v, %v; want %v", got, err, want)
	}

	dir := t.TempDir()
	for i := range maxHAProxyCerts + 1 {
		writeCertFile(t, dir, fmt.Sprintf("%03d.pem", i), nil)
	}
	haproxyConfigFile(t, "frontend https\n  bind :443 ssl crt "+dir+"\n")
	if got, err := haproxyCerts(ctx, unit); err == nil || !strings.Contains(err.Error(), "more than") {
		t.Errorf("haproxy_certs of %d files = %v, %v; want an error", maxHAProxyCerts+1, got, err)
	}

	if _, err := haproxyCerts(ctx, Target{Kind: kindUnit, Name: "nginx.service"}); !errors.Is(err, ErrUnsupported) {
		t.Errorf("haproxy_certs of nginx = %v, want ErrUnsupported", err)
	}
	broken := writeCertFile(t, dir, "x.pem", []byte("no certificate\n"))
	haproxyConfigFile(t, "bind :443 ssl crt "+broken+"\n")
	if got, err := haproxyCerts(ctx, unit); err == nil || strings.Contains(err.Error(), dir) {
		t.Errorf("haproxy_certs of a file without a certificate = %v, %v; want an error without its path", got, err)
	}
}
