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

// haproxyCertAnswer is HAProxy's answer to show ssl cert <name> for a certificate ending at end, the
// form of the Management Guide's example.
func haproxyCertAnswer(name string, end time.Time) string {
	return "Filename: " + name + "\nStatus: Used\nSerial: 03ECC19BA54B25E85ABA46EE561B9A10D26F\n" +
		"notBefore: Sep 13 21:20:24 2019 GMT\nnotAfter: " + end.UTC().Format(haproxyNotAfterLayout) +
		"\nSubject: /CN=x\nSHA1 FingerPrint: 417A11CAE25F607B24F638B4A8AEE51D1E211477\n\n"
}

func TestHAProxyCertsCountsTheFilesHAProxyDidNotReload(t *testing.T) {
	stubNow(t, start)
	dir := t.TempDir()
	day := 24 * time.Hour
	renewed := writeCertFile(t, dir, "renewed.pem", namedCertPEM(t, "a.example.org", start.Add(90*day), true))
	same := writeCertFile(t, dir, "same.pem", namedCertPEM(t, "b.example.org", start.Add(30*day), true))
	unlisted := writeCertFile(t, dir, "unlisted.pem", namedCertPEM(t, "c.example.org", start.Add(80*day), true))
	// The file older than what HAProxy has loaded (it was replaced by hand): no reload is missing.
	older := writeCertFile(t, dir, "older.pem", namedCertPEM(t, "d.example.org", start.Add(10*day), true))
	haproxyConfigFile(t, "global\n  stats socket /run/haproxy/admin.sock mode 660 level operator\n"+
		"frontend https\n  bind :443 ssl crt "+renewed+" crt "+same+" crt "+unlisted+" crt "+older+"\n")
	answers := map[string]string{
		"show ssl cert":            "# transaction\n*" + unlisted + "\n# filename\n" + renewed + "\n" + same + "\n" + older + "\n/etc/other.pem\n",
		"show ssl cert " + renewed: haproxyCertAnswer(renewed, start.Add(20*day)),
		"show ssl cert " + same:    haproxyCertAnswer(same, start.Add(30*day)),
		"show ssl cert " + older:   haproxyCertAnswer(older, start.Add(40*day)),
	}
	_, sent := stubHAProxy(t, "/run/haproxy/admin.sock", answers)

	got, err := haproxyCerts(context.Background(), Target{Kind: kindUnit, Name: "haproxy.service"})
	if err != nil || got["reload_missing"] != 1 || got["certs"] != 4 {
		t.Errorf("haproxy_certs = %v, %v; want reload_missing 1 of 4 certs", got, err)
	}
	for _, cmd := range *sent {
		if strings.Contains(cmd, unlisted) || strings.Contains(cmd, "other.pem") {
			t.Errorf("asked %q: only files of the bind lines that HAProxy lists are asked", cmd)
		}
	}
}

func TestHAProxyCertsWithoutAnAnswerOfTheSocketHasNoReloadField(t *testing.T) {
	stubNow(t, start)
	dir := t.TempDir()
	file := writeCertFile(t, dir, "a.pem", namedCertPEM(t, "a.example.org", start.Add(90*24*time.Hour), true))
	cfg := "frontend https\n  bind :443 ssl crt " + file + "\n"
	ctx, unit := context.Background(), Target{Kind: kindUnit, Name: "haproxy.service"}
	for name, answers := range map[string]map[string]string{
		"refused":       {"show ssl cert": "Can't allocate memory!\n\n"},
		"unknown":       {"show ssl cert": "Unknown command. Please enter one of the following commands only :\n"},
		"other file":    {"show ssl cert": "# filename\n" + file + "\n", "show ssl cert " + file: haproxyCertAnswer("/etc/x.pem", start)},
		"no notAfter":   {"show ssl cert": "# filename\n" + file + "\n", "show ssl cert " + file: "Filename: " + file + "\n\n"},
		"not listed":    {"show ssl cert": "# filename\n/etc/x.pem\n"},
		"detail denied": {"show ssl cert": "# filename\n" + file + "\n", "show ssl cert " + file: "Permission denied\n\n"},
	} {
		haproxyConfigFile(t, "global\n  stats socket /run/h.sock\n"+cfg)
		stubHAProxy(t, "/run/h.sock", answers)
		got, err := haproxyCerts(ctx, unit)
		if _, has := got["reload_missing"]; err != nil || has || got["certs"] != 1 {
			t.Errorf("%s: haproxy_certs = %v, %v; want the certificate without reload_missing", name, got, err)
		}
	}
	haproxyConfigFile(t, cfg)
	if got, err := haproxyCerts(ctx, unit); err != nil || got["reload_missing"] != nil {
		t.Errorf("without a stats socket: haproxy_certs = %v, %v; want no reload_missing", got, err)
	}
}

func TestHAProxyCertEndReadsNotAfterOfThatFile(t *testing.T) {
	answer := []byte("Filename: /etc/a.pem\nStatus: Used\nnotBefore: Sep 13 21:20:24 2019 GMT\nnotAfter: Dec  2 21:20:24 2019 GMT\n")
	end, ok := haproxyCertEnd(answer, "/etc/a.pem")
	if want := time.Date(2019, 12, 2, 21, 20, 24, 0, time.UTC); !ok || !end.Equal(want) {
		t.Errorf("notAfter = %v, %v; want %v", end, ok, want)
	}
	if _, ok := haproxyCertEnd(answer, "/etc/b.pem"); ok {
		t.Error("the answer for another file was taken")
	}
}
